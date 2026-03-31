from __future__ import annotations

import json
import logging
import socket
import fcntl
import struct
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import cv2

from signomat_pi.ble_control_service.service import BLEControlService
from signomat_pi.capture_service.service import CaptureService
from signomat_pi.common.config import SignomatConfig, resolve_repo_path
from signomat_pi.common.database import Database
from signomat_pi.common.lcd import LCDStatusDisplay
from signomat_pi.common.storage import StorageManager
from signomat_pi.common.utils import stable_id, utc_now, utc_now_text
from signomat_pi.gps_service.service import GPSService
from signomat_pi.inference_service.service import InferenceService
from signomat_pi.sync_service.service import SyncService


LOGGER = logging.getLogger(__name__)


class RuntimeCallbacks:
    def __init__(self, runtime: "SignomatRuntime"):
        self.runtime = runtime

    def current_trip_id(self) -> str | None:
        return self.runtime.current_trip_id

    def on_detection(self, payload: dict) -> None:
        self.runtime.on_detection(payload)


class SignomatRuntime:
    def __init__(self, config: SignomatConfig):
        self.config = config
        self.storage = StorageManager(config)
        self.storage.initialize()
        self.database = Database(self.storage.db_path, resolve_repo_path("pi/migrations"))
        self.database.apply_migrations()
        self.database.recover_interrupted_trips()
        self.current_trip_id: str | None = None
        self.recording_active = False
        self.inference_active = config.inference.enabled
        self.detection_count_trip = 0
        self.last_detection: dict | None = None
        self._wifi_connected = False
        self._wifi_checked_at = 0.0
        self.lcd = LCDStatusDisplay()
        self.lcd_running = threading.Event()
        self.lcd_thread: threading.Thread | None = None
        self.sync_service = SyncService(config, self.database)
        self.capture_service = CaptureService(config, self.storage, self.database)
        self.gps_service = GPSService(config, self.storage, self.database)
        self.inference_service = InferenceService(config, self.storage, self.database, self.capture_service, self.gps_service, RuntimeCallbacks(self))
        self.ble_service = BLEControlService(config, self)
        if self.lcd.enabled and not self.lcd.available and self.lcd.error:
            LOGGER.warning("LCD unavailable: %s", self.lcd.error)
        self.database.replace_model_versions(
            [
                ("candidate_detector", "heuristic-color-shape-v1", "local"),
                ("classifier", "heuristic-sign-classifier-v1", "local"),
                ("taxonomy", f"taxonomy-v{self.inference_service.taxonomy.version}", "config"),
            ]
        )
        self.database.replace_taxonomy_snapshot(self.inference_service.taxonomy.version, self.inference_service.taxonomy.snapshot_entries())

    def start(self) -> None:
        self.lcd.show_startup_stage("Starting", "capture")
        self.capture_service.start()
        self.lcd.show_startup_stage("Starting", "gps")
        self.gps_service.start()
        self.lcd.show_startup_stage("Starting", "inference")
        self.inference_service.start()
        if self.config.ble.enabled:
            self.ble_service.start()
        self.sync_service.start()
        self._start_lcd_loop()
        self.lcd.show_ready("Runtime ready")
        self.database.add_device_event("runtime.start", "info", "runtime started")

    def stop(self) -> None:
        if self.current_trip_id:
            self.stop_trip()
        self._stop_lcd_loop()
        self.inference_service.stop()
        self.gps_service.stop()
        self.capture_service.stop()
        if self.config.ble.enabled:
            self.ble_service.stop()
        self.sync_service.stop()
        self.database.add_device_event("runtime.stop", "info", "runtime stopped")
        self.lcd.close()
        self.database.close()

    def create_trip_id(self) -> str:
        day_prefix = utc_now().date().isoformat()
        seq = self.database.next_trip_sequence(day_prefix)
        return f"{day_prefix}_trip_{seq:03d}"

    def start_trip(self) -> dict:
        if self.current_trip_id:
            return {"ok": True, "trip_id": self.current_trip_id, "message": "trip already active"}
        trip_id = self.create_trip_id()
        self.current_trip_id = trip_id
        self.detection_count_trip = 0
        self.last_detection = None
        self.database.create_trip(trip_id, True, self.inference_active)
        self.database.enqueue_upload("trip_metadata", None, "trips", trip_id, {"trip_id": trip_id})
        self.capture_service.set_trip(trip_id)
        self.gps_service.set_trip(trip_id)
        self.capture_service.start_recording()
        self.recording_active = True
        self.database.add_device_event("trip.start", "info", "trip started", {"trip_id": trip_id})
        self.lcd.show_message("Trip started", trip_id[-8:], transient_seconds=2, force=True)
        self.refresh_lcd()
        self.ble_service.refresh()
        return {"ok": True, "trip_id": trip_id}

    def stop_trip(self) -> dict:
        if not self.current_trip_id:
            return {"ok": True, "message": "no active trip"}
        trip_id = self.current_trip_id
        self.capture_service.stop_recording()
        self.capture_service.set_trip(None)
        self.gps_service.set_trip(None)
        self.database.stop_trip(trip_id)
        self.database.enqueue_upload("trip_metadata", None, "trips", trip_id, {"trip_id": trip_id})
        self.database.add_device_event("trip.stop", "info", "trip stopped", {"trip_id": trip_id})
        self.current_trip_id = None
        self.recording_active = False
        self.lcd.show_message("Trip stopped", trip_id[-8:], transient_seconds=2, force=True)
        self.refresh_lcd()
        self.ble_service.refresh()
        return {"ok": True, "trip_id": trip_id}

    def start_recording(self) -> dict:
        if not self.current_trip_id:
            return {"ok": False, "message": "start a trip first"}
        self.capture_service.start_recording()
        self.recording_active = True
        self.database.add_device_event("recording.start", "info", "recording enabled", {"trip_id": self.current_trip_id})
        self.refresh_lcd()
        self.ble_service.refresh()
        return {"ok": True}

    def stop_recording(self) -> dict:
        self.capture_service.stop_recording()
        self.recording_active = False
        self.database.add_device_event("recording.stop", "info", "recording disabled", {"trip_id": self.current_trip_id})
        self.refresh_lcd()
        self.ble_service.refresh()
        return {"ok": True}

    def enable_inference(self) -> dict:
        self.inference_active = True
        self.inference_service.set_enabled(True)
        self.database.add_device_event("inference.enable", "info", "inference enabled")
        self.refresh_lcd()
        self.ble_service.refresh()
        return {"ok": True}

    def disable_inference(self) -> dict:
        self.inference_active = False
        self.inference_service.set_enabled(False)
        self.database.add_device_event("inference.disable", "info", "inference disabled")
        self.refresh_lcd()
        self.ble_service.refresh()
        return {"ok": True}

    def on_detection(self, payload: dict) -> None:
        self.detection_count_trip += 1
        self.last_detection = {
            "event_id": payload["event_id"],
            "category_label": payload["category_label"],
            "specific_label": payload["specific_label"],
            "timestamp_utc": payload["timestamp_utc"],
        }
        label = payload["specific_label"] or payload["category_label"]
        self.lcd.show_saved_event(label)
        self.refresh_lcd()
        self.ble_service.refresh()

    def diagnostic_snapshot(self) -> dict:
        base_trip = self.current_trip_id or "no_trip"
        snapshot_dir = self.storage.trip_paths(base_trip)["diagnostics"] / utc_now_text().replace(":", "-")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        packet = self.capture_service.latest_frame()
        latest = self.last_detection
        clean_path = None
        annotated_path = None
        if packet is not None:
            clean_path = snapshot_dir / "clean.jpg"
            cv2.imwrite(str(clean_path), packet.frame)
            if latest:
                event = self.database.detection_by_id(latest["event_id"])
                if event:
                    annotated = packet.frame.copy()
                    cv2.rectangle(
                        annotated,
                        (event["bbox_left"], event["bbox_top"]),
                        (event["bbox_right"], event["bbox_bottom"]),
                        (0, 255, 0),
                        2,
                    )
                    cv2.putText(
                        annotated,
                        event["category_label"],
                        (event["bbox_left"], max(24, event["bbox_top"] - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 0),
                        2,
                    )
                    annotated_path = snapshot_dir / "annotated.jpg"
                    cv2.imwrite(str(annotated_path), annotated)
        status_path = snapshot_dir / "status.json"
        status_path.write_text(json.dumps(self.status_snapshot(), indent=2), encoding="utf-8")
        latest_gps = self.gps_service.latest_sample()
        gps_path = snapshot_dir / "gps.json"
        gps_path.write_text(json.dumps(asdict(latest_gps) if latest_gps else {}, indent=2), encoding="utf-8")
        model_versions = self.database.query_all("SELECT component, version_label, source FROM model_versions ORDER BY component")
        (snapshot_dir / "model_versions.json").write_text(json.dumps([dict(row) for row in model_versions], indent=2), encoding="utf-8")
        recent_events = self.database.recent_device_events(limit=20)
        (snapshot_dir / "logs_excerpt.json").write_text(json.dumps(recent_events, indent=2), encoding="utf-8")
        self.database.add_device_event("diagnostic.snapshot", "info", "diagnostic snapshot saved", {"path": str(snapshot_dir)})
        self.ble_service.refresh()
        return {
            "ok": True,
            "snapshot_dir": self.storage.relative_path(snapshot_dir),
            "clean_frame": self.storage.relative_path(clean_path),
            "annotated_frame": self.storage.relative_path(annotated_path),
        }

    def dispatch_command(self, command: str) -> dict:
        handlers = {
            "start_trip": self.start_trip,
            "stop_trip": self.stop_trip,
            "start_recording": self.start_recording,
            "stop_recording": self.stop_recording,
            "enable_inference": self.enable_inference,
            "disable_inference": self.disable_inference,
            "save_diagnostic_snapshot": self.diagnostic_snapshot,
        }
        handler = handlers.get(command)
        if handler is None:
            return {"ok": False, "message": f"unknown command: {command}"}
        return handler()

    def temperature_c(self) -> float | None:
        path = Path("/sys/class/thermal/thermal_zone0/temp")
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        try:
            return round(int(raw) / 1000.0, 1)
        except ValueError:
            return None

    def wifi_connected(self) -> bool:
        now = time.monotonic()
        if now - self._wifi_checked_at < 5.0:
            return self._wifi_connected
        interface = self.config.app.wifi_interface
        self._wifi_checked_at = now
        if not interface:
            self._wifi_connected = False
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = struct.pack("256s", interface[:15].encode("utf-8"))
            fcntl.ioctl(sock.fileno(), 0x8915, packed)
            self._wifi_connected = True
        except OSError:
            self._wifi_connected = False
        finally:
            sock.close()
        return self._wifi_connected

    def status_snapshot(self) -> dict:
        storage = self.storage.storage_status()
        sync = self.sync_service.status()
        return {
            "trip_active": self.current_trip_id is not None,
            "recording_active": self.recording_active,
            "inference_active": self.inference_active,
            "current_trip_id": self.current_trip_id,
            "detection_count_trip": self.detection_count_trip,
            "last_detection_label": (self.last_detection["specific_label"] or self.last_detection["category_label"]) if self.last_detection else None,
            "last_detection_timestamp": self.last_detection["timestamp_utc"] if self.last_detection else None,
            "storage": storage,
            "upload_queue_size": sync.get("total", 0),
            "sync_status": sync["last_result"],
            "gps_health": self.gps_service.health,
            "pi_temperature_c": self.temperature_c(),
            "ble_connected": self.ble_service.connected if self.config.ble.enabled else False,
            "wifi_connected": self.wifi_connected(),
        }

    def health(self) -> dict:
        return {
            "ok": True,
            "camera": self.capture_service.camera.describe(),
            "gps_health": self.gps_service.health,
            "trip_active": bool(self.current_trip_id),
            "storage": self.storage.storage_status(),
        }

    def refresh_lcd(self) -> None:
        gps = self.gps_service.latest_sample()
        last_label = None
        if self.last_detection:
            last_label = self.last_detection["specific_label"] or self.last_detection["category_label"]
        sync_status = self.sync_service.status()["last_result"]
        self.lcd.update_runtime(
            gps_health=self.gps_service.health,
            speed_mps=gps.speed if gps else None,
            event_count=self.detection_count_trip,
            last_label=last_label,
            trip_active=self.current_trip_id is not None,
            recording_active=self.recording_active,
            inference_active=self.inference_active,
            ble_connected=self.ble_service.connected if self.config.ble.enabled else False,
            wifi_connected=self.wifi_connected(),
            sync_status=sync_status,
        )

    def _lcd_loop(self) -> None:
        while self.lcd_running.is_set():
            self.refresh_lcd()
            time.sleep(self.lcd.refresh_interval)

    def _start_lcd_loop(self) -> None:
        self.lcd_running.set()
        self.lcd_thread = threading.Thread(target=self._lcd_loop, name="lcd-refresh", daemon=True)
        self.lcd_thread.start()

    def _stop_lcd_loop(self) -> None:
        self.lcd_running.clear()
        if self.lcd_thread:
            self.lcd_thread.join(timeout=2)
