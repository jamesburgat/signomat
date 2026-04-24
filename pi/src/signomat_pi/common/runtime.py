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
from signomat_pi.inference_service.replay import ReplayEvaluator
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
        self._wifi_ipv4: str | None = None
        self._wifi_checked_at = 0.0
        self.lcd = LCDStatusDisplay()
        self.lcd_running = threading.Event()
        self.lcd_thread: threading.Thread | None = None
        self.sync_service = SyncService(config, self.database)
        self.capture_service = CaptureService(config, self.storage, self.database)
        self.gps_service = GPSService(config, self.storage, self.database)
        self.inference_service = InferenceService(config, self.storage, self.database, self.capture_service, self.gps_service, RuntimeCallbacks(self))
        self.replay_evaluator = ReplayEvaluator(config, self.storage, self.database, classifier=self.inference_service.classifier)
        self.ble_service = BLEControlService(config, self)
        if self.lcd.enabled and not self.lcd.available and self.lcd.error:
            LOGGER.warning("LCD unavailable: %s", self.lcd.error)
        self.database.replace_model_versions(
            [
                *self.inference_service.model_versions(),
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

    def camera_tuning(self) -> dict:
        return {
            "ok": True,
            "persisted": False,
            "message": "live camera tuning updates apply immediately but are not saved across service restarts",
            "tuning": self.capture_service.camera_tuning(),
        }

    def update_camera_tuning(self, updates: dict) -> dict:
        tuning = self.capture_service.update_camera_tuning(updates)
        self.config.camera.auto_exposure = tuning["auto_exposure"]
        self.config.camera.exposure_compensation = tuning["exposure_compensation"]
        self.config.camera.brightness = tuning["brightness"]
        self.config.camera.contrast = tuning["contrast"]
        self.config.camera.exposure_time_us = tuning["exposure_time_us"]
        self.config.camera.analogue_gain = tuning["analogue_gain"]
        self.database.add_device_event("camera.tuning", "info", "camera tuning updated", tuning)
        return {
            "ok": True,
            "persisted": False,
            "message": "live camera tuning updated for the running session",
            "tuning": tuning,
        }

    def on_detection(self, payload: dict) -> None:
        self.detection_count_trip += 1
        self.last_detection = {
            "event_id": payload["event_id"],
            "category_label": payload["category_label"],
            "specific_label": payload["specific_label"],
            "timestamp_utc": payload["timestamp_utc"],
        }
        label = payload["specific_label"] or payload["category_label"]
        if self._is_classified_detection(payload):
            self.lcd.show_classified_event(label)
        self.refresh_lcd()
        self.ble_service.refresh()

    def _is_classified_detection(self, payload: dict) -> bool:
        label = payload.get("specific_label") or payload.get("category_label")
        raw_label = payload.get("raw_classifier_label")
        return bool(label and label != "unknown_sign" and raw_label != "unknown_sign")

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

    def replay_trip(self, trip_id: str, *, export: bool = True) -> dict:
        return self.replay_evaluator.evaluate_trip(trip_id, export=export)

    def temperature_c(self) -> float | None:
        path = Path("/sys/class/thermal/thermal_zone0/temp")
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        try:
            return round(int(raw) / 1000.0, 1)
        except ValueError:
            return None

    def memory_status(self) -> dict[str, int | None]:
        values: dict[str, int | None] = {"available_mb": None, "total_mb": None}
        path = Path("/proc/meminfo")
        if not path.exists():
            return values
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            key, _, rest = line.partition(":")
            if key not in {"MemAvailable", "MemTotal"}:
                continue
            parts = rest.strip().split()
            if not parts:
                continue
            try:
                mb = int(parts[0]) // 1024
            except ValueError:
                continue
            if key == "MemAvailable":
                values["available_mb"] = mb
            elif key == "MemTotal":
                values["total_mb"] = mb
        return values

    def system_alerts(self, storage: dict | None = None, sync: dict | None = None, memory: dict | None = None) -> list[dict]:
        storage = storage or self.storage.storage_status()
        sync = sync or self.sync_service.status()
        memory = memory or self.memory_status()
        alerts: list[dict] = []
        inference = self.inference_service.status()
        if inference["health"] != "ok":
            alerts.append(
                {
                    "id": "inference_error",
                    "level": "critical",
                    "symbol": "/!\\",
                    "title": "YOLO fault",
                    "message": inference["last_error"] or "Inference model unavailable",
                    "lcd_title": "YOLO fault",
                    "lcd_message": f"Model error: {inference['last_error'] or 'inference unavailable'}",
                }
            )
        free_mb = storage.get("free_mb", 0)
        if free_mb < self.config.camera.low_storage_stop_mb:
            alerts.append(
                {
                    "id": "storage_low",
                    "level": "warning",
                    "symbol": "/!\\",
                    "title": "Storage low",
                    "message": f"{free_mb} MB free",
                    "lcd_title": "Low storage",
                    "lcd_message": f"{free_mb}MB free below {self.config.camera.low_storage_stop_mb}MB stop limit",
                }
            )
        available_mb = memory.get("available_mb")
        if available_mb is not None and available_mb < self.config.app.low_memory_warn_mb:
            alerts.append(
                {
                    "id": "memory_low",
                    "level": "warning",
                    "symbol": "/!\\",
                    "title": "Memory low",
                    "message": f"{available_mb} MB available",
                    "lcd_title": "Low memory",
                    "lcd_message": f"{available_mb}MB RAM below {self.config.app.low_memory_warn_mb}MB warning",
                }
            )
        if sync.get("last_result") == "error":
            sync_error = sync.get("last_error") or "Upload sync failed"
            alerts.append(
                {
                    "id": "sync_error",
                    "level": "warning",
                    "symbol": "/!\\",
                    "title": "Sync error",
                    "message": sync_error,
                    "lcd_title": "Sync error",
                    "lcd_message": f"Upload failed: {sync_error}",
                }
            )
        return alerts

    def _refresh_network_state(self) -> None:
        now = time.monotonic()
        if now - self._wifi_checked_at < 5.0:
            return
        interface = self.config.app.wifi_interface
        self._wifi_checked_at = now
        if not interface:
            self._wifi_connected = False
            self._wifi_ipv4 = None
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = struct.pack("256s", interface[:15].encode("utf-8"))
            response = fcntl.ioctl(sock.fileno(), 0x8915, packed)
            self._wifi_connected = True
            self._wifi_ipv4 = socket.inet_ntoa(response[20:24])
        except OSError:
            self._wifi_connected = False
            self._wifi_ipv4 = None
        finally:
            sock.close()

    def wifi_connected(self) -> bool:
        self._refresh_network_state()
        return self._wifi_connected

    def wifi_ipv4_address(self) -> str | None:
        self._refresh_network_state()
        return self._wifi_ipv4

    def preview_hostname(self) -> str | None:
        hostname = socket.gethostname().strip()
        if not hostname:
            return None
        if hostname.endswith(".local") or "." in hostname:
            return hostname
        return f"{hostname}.local"

    def preview_base_url(self) -> str | None:
        hostname = self.preview_hostname()
        if not hostname:
            return None
        return f"http://{hostname}:{self.config.api.port}"

    def preview_fallback_base_url(self) -> str | None:
        ip_address = self.wifi_ipv4_address()
        if not ip_address:
            return None
        return f"http://{ip_address}:{self.config.api.port}"

    def status_snapshot(self) -> dict:
        storage = self.storage.storage_status()
        sync = self.sync_service.status()
        memory = self.memory_status()
        alerts = self.system_alerts(storage=storage, sync=sync, memory=memory)
        if self.current_trip_id:
            sign_categories = self.database.detection_category_counts_for_trip(self.current_trip_id)
            recent_signs = self.database.recent_detections_for_trip(self.current_trip_id)
        else:
            sign_categories = []
            recent_signs = []
        return {
            "trip_active": self.current_trip_id is not None,
            "recording_active": self.recording_active,
            "inference_active": self.inference_active,
            "current_trip_id": self.current_trip_id,
            "detection_count_trip": self.detection_count_trip,
            "last_detection_label": (self.last_detection["specific_label"] or self.last_detection["category_label"]) if self.last_detection else None,
            "last_detection_timestamp": self.last_detection["timestamp_utc"] if self.last_detection else None,
            "trip_sign_categories": sign_categories,
            "trip_recent_signs": recent_signs,
            "storage": storage,
            "memory": memory,
            "upload_queue_size": sync.get("total", 0),
            "sync_status": sync["last_result"],
            "gps_health": self.gps_service.health,
            "pi_temperature_c": self.temperature_c(),
            "inference_health": self.inference_service.status(),
            "alerts": alerts,
            "primary_alert": alerts[0] if alerts else None,
            "ble_connected": self.ble_service.connected if self.config.ble.enabled else False,
            "wifi_connected": self.wifi_connected(),
            "preview_base_url": self.preview_base_url(),
            "preview_fallback_base_url": self.preview_fallback_base_url(),
        }

    def health(self) -> dict:
        return {
            "ok": not bool(self.system_alerts(storage=self.storage.storage_status())),
            "camera": self.capture_service.camera.describe(),
            "gps_health": self.gps_service.health,
            "trip_active": bool(self.current_trip_id),
            "primary_alert": self.status_snapshot()["primary_alert"],
            "storage": self.storage.storage_status(),
        }

    def refresh_lcd(self) -> None:
        gps = self.gps_service.latest_sample()
        last_label = None
        if self.last_detection:
            last_label = self.last_detection["specific_label"] or self.last_detection["category_label"]
        sync_status = self.sync_service.status()["last_result"]
        primary_alert = self.status_snapshot()["primary_alert"]
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
            alert=primary_alert,
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
