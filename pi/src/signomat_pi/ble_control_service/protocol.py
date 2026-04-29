from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


DEVICE_SERVICE_UUID = "7b1e0001-5d1f-4aa0-9a7d-6f5c0b6c1000"
SESSION_SERVICE_UUID = "7b1e0002-5d1f-4aa0-9a7d-6f5c0b6c1000"
DIAGNOSTICS_SERVICE_UUID = "7b1e0003-5d1f-4aa0-9a7d-6f5c0b6c1000"

DEVICE_STATUS_CHAR_UUID = "7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000"
SESSION_STATE_CHAR_UUID = "7b1e1002-5d1f-4aa0-9a7d-6f5c0b6c1000"
COMMAND_CHAR_UUID = "7b1e1003-5d1f-4aa0-9a7d-6f5c0b6c1000"
DETECTION_SUMMARY_CHAR_UUID = "7b1e1004-5d1f-4aa0-9a7d-6f5c0b6c1000"
UPLOAD_SUMMARY_CHAR_UUID = "7b1e1005-5d1f-4aa0-9a7d-6f5c0b6c1000"
STORAGE_STATUS_CHAR_UUID = "7b1e1006-5d1f-4aa0-9a7d-6f5c0b6c1000"
GPS_STATUS_CHAR_UUID = "7b1e1007-5d1f-4aa0-9a7d-6f5c0b6c1000"


@dataclass
class CommandEnvelope:
    cmd: str

    @classmethod
    def parse(cls, raw: bytes) -> "CommandEnvelope":
        data = json.loads(raw.decode("utf-8"))
        return cls(cmd=data["cmd"])

    def serialize(self) -> bytes:
        return json.dumps({"cmd": self.cmd}, separators=(",", ":")).encode("utf-8")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def device_status_payload(status: dict[str, Any]) -> dict[str, Any]:
    classification = status.get("classification_status") or {}
    return {
        "ble": status["ble_connected"],
        "inf": status["inference_active"],
        "sync": status["sync_status"],
        "temp_c": status["pi_temperature_c"],
        "alert": status.get("primary_alert"),
        "mode": status.get("pi_mode"),
        "mode_detail": status.get("pi_mode_detail"),
        "class_state": classification.get("state"),
        "class_running": classification.get("running"),
        "class_trip_id": classification.get("current_trip_id"),
        "class_stage": classification.get("current_stage"),
        "class_processed": classification.get("processed_groups"),
        "class_total": classification.get("total_groups"),
        "class_pct": classification.get("progress_pct"),
        "class_pending": classification.get("pending_trip_count"),
        "class_queue": len(classification.get("queued_trip_ids") or []),
        "class_launchable": classification.get("launchable"),
        "class_last_completed_trip_id": classification.get("last_completed_trip_id"),
        "class_last_completed_at": classification.get("last_completed_at"),
        "class_last_error": classification.get("last_error"),
        "preview_base_url": status.get("preview_base_url"),
        "preview_fallback_base_url": status.get("preview_fallback_base_url"),
    }


def session_state_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "trip": status["trip_active"],
        "rec": status["recording_active"],
        "trip_id": status["current_trip_id"],
        "det": status["detection_count_trip"],
    }


def detection_summary_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "det": status["detection_count_trip"],
        "last": status["last_detection_label"],
        "last_ts": status["last_detection_timestamp"],
        "cats": {item["category_label"]: item["count"] for item in status.get("trip_sign_categories", [])},
        "recent": [
            {
                "id": item["event_id"],
                "label": item["specific_label"] or item["category_label"],
                "category": item["category_label"],
                "ts": item["timestamp_utc"],
                "conf": item["classifier_confidence"],
            }
            for item in status.get("trip_recent_signs", [])
        ],
    }


def upload_summary_payload(status: dict[str, Any]) -> dict[str, Any]:
    upload = status.get("upload_progress") or {}
    return {
        "queue": status["upload_queue_size"],
        "sync": status["sync_status"],
        "pending": upload.get("pending", 0),
        "synced": upload.get("synced", 0),
        "total": upload.get("total", 0),
        "pct": upload.get("progress_pct", 0),
        "last_synced_at": upload.get("last_synced_at"),
    }


def storage_status_payload(status: dict[str, Any]) -> dict[str, Any]:
    storage = status["storage"]
    return {
        "free_mb": storage["free_mb"],
        "used_mb": storage["used_mb"],
        "total_mb": storage["total_mb"],
    }


def gps_status_payload(status: dict[str, Any], latest_gps: Any | None = None) -> dict[str, Any]:
    payload = {
        "gps": status["gps_health"],
        "fix": status["gps_health"] == "fix",
        "lat": None,
        "lon": None,
        "spd": None,
        "head": None,
    }
    if latest_gps is not None:
        payload.update(
            {
                "lat": latest_gps.lat,
                "lon": latest_gps.lon,
                "spd": latest_gps.speed,
                "head": latest_gps.heading,
            }
        )
    return payload


def characteristic_payloads(status: dict[str, Any], latest_gps: Any | None = None) -> dict[str, dict[str, Any]]:
    return {
        DEVICE_STATUS_CHAR_UUID: device_status_payload(status),
        SESSION_STATE_CHAR_UUID: session_state_payload(status),
        DETECTION_SUMMARY_CHAR_UUID: detection_summary_payload(status),
        UPLOAD_SUMMARY_CHAR_UUID: upload_summary_payload(status),
        STORAGE_STATUS_CHAR_UUID: storage_status_payload(status),
        GPS_STATUS_CHAR_UUID: gps_status_payload(status, latest_gps),
    }


def characteristic_payload_bytes(status: dict[str, Any], latest_gps: Any | None = None) -> dict[str, bytes]:
    return {uuid: _json_bytes(payload) for uuid, payload in characteristic_payloads(status, latest_gps).items()}


def compact_status(status: dict[str, Any], latest_gps: Any | None = None) -> bytes:
    payload = {
        **device_status_payload(status),
        **session_state_payload(status),
        **detection_summary_payload(status),
        **upload_summary_payload(status),
        **storage_status_payload(status),
        **gps_status_payload(status, latest_gps),
    }
    return _json_bytes(payload)
