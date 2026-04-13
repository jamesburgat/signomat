from __future__ import annotations

import http.client
import hashlib
import json
import logging
import mimetypes
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error, parse, request

from signomat_pi.common.config import resolve_repo_path

LOGGER = logging.getLogger(__name__)


class SyncService:
    def __init__(self, config, database):
        self.config = config
        self.database = database
        self.last_result = "idle"
        self.last_synced_at: str | None = None
        self.last_error: str | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.base_data_dir = resolve_repo_path(config.app.base_data_dir)

    def status(self) -> dict:
        summary = self.database.upload_status()
        summary["last_result"] = self.last_result
        summary["last_synced_at"] = self.last_synced_at
        summary["last_error"] = self.last_error
        summary["enabled"] = self.config.sync.enabled
        return summary

    def start(self) -> None:
        if not self.config.sync.enabled or not self.config.sync.base_url or not self.config.sync.ingest_token:
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._sync_loop, name="sync-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None

    def force_sync(self) -> dict:
        if not self.config.sync.enabled:
            self.last_result = "disabled"
            return {"ok": False, "message": "sync is disabled"}
        if not self.config.sync.base_url or not self.config.sync.ingest_token:
            self.last_result = "misconfigured"
            self.last_error = "missing sync base URL or ingest token"
            return {"ok": False, "message": self.last_error}
        return self._run_once()

    def _sync_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                pending = self.database.upload_status().get("pending", 0)
                if pending > 0:
                    self._run_once()
            except Exception as exc:  # pragma: no cover - defensive background path
                LOGGER.exception("background sync failed: %s", exc)
                self.last_result = "error"
                self.last_error = str(exc)
            self.stop_event.wait(self.config.sync.interval_seconds)

    def _run_once(self) -> dict:
        media_result = self._run_media_uploads()
        metadata_result = self._run_metadata_sync()
        total_media = media_result["counts"]["items"]
        total_metadata = metadata_result["counts"]["items"]
        total_items = total_media + total_metadata
        any_error = (not media_result["ok"]) or (not metadata_result["ok"])
        details = {
            "media": media_result,
            "metadata": metadata_result,
        }
        if total_items == 0:
            self.last_result = "idle"
            self.last_error = None
            return {"ok": True, "message": "no upload items pending", "counts": {"items": 0}, "details": details}
        synced_media = media_result["counts"].get("synced", 0)
        synced_metadata = metadata_result["counts"].get("synced", metadata_result["counts"].get("items", 0) if metadata_result["ok"] else 0)
        if any_error:
            self.last_result = "partial" if (synced_media + synced_metadata) > 0 else "error"
            self.last_error = media_result.get("message") or metadata_result.get("message")
            return {"ok": False, "message": self.last_error, "counts": {"items": total_items}, "details": details}
        self.last_result = "synced"
        self.last_error = None
        self.last_synced_at = _utc_now_text()
        return {"ok": True, "counts": {"items": total_items}, "details": details}

    def _run_media_uploads(self) -> dict:
        media_items = self.database.pending_upload_items(
            limit=self.config.sync.batch_size,
            item_types=("media_asset", "video_media"),
        )
        if not media_items:
            return {"ok": True, "counts": {"items": 0, "synced": 0}}

        synced = 0
        errors: list[str] = []
        for item in media_items:
            queue_id = item["queue_id"]
            local_path = item.get("local_path")
            if not local_path:
                message = "upload queue item missing local_path"
                self._mark_upload_failure([queue_id], item["retry_count"], message)
                errors.append(message)
                continue
            absolute_path = self._absolute_local_path(local_path)
            if not absolute_path.exists():
                message = f"media file missing on disk: {local_path}"
                self._mark_upload_failure([queue_id], item["retry_count"], message)
                errors.append(message)
                continue
            bucket = _bucket_name_for_path(local_path)
            content_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
            try:
                self._put_media(bucket=bucket, key=local_path, file_path=absolute_path, content_type=content_type)
            except Exception as exc:
                message = str(exc)
                self._mark_upload_failure([queue_id], item["retry_count"], message)
                errors.append(message)
                continue
            self.database.mark_upload_items_state([queue_id], "synced", last_error=None)
            self._advance_related_upload_state_after_media(item["related_table"], item["related_id"])
            synced += 1

        return {
            "ok": not errors,
            "message": errors[0] if errors else None,
            "counts": {"items": len(media_items), "synced": synced},
        }

    def _run_metadata_sync(self) -> dict:
        metadata_items = self.database.pending_upload_items(
            limit=self.config.sync.batch_size,
            item_types=("trip_metadata", "detection_metadata", "video_segment"),
        )
        if not metadata_items:
            return {"ok": True, "message": "no metadata items pending", "counts": {"items": 0}}

        queue_ids = [item["queue_id"] for item in metadata_items]
        trip_ids = sorted({item["related_id"] for item in metadata_items if item["related_table"] == "trips"})
        event_ids = sorted({item["related_id"] for item in metadata_items if item["related_table"] == "detections"})
        video_segment_ids = sorted({item["related_id"] for item in metadata_items if item["related_table"] == "video_segments"})

        detections = self.database.detections_by_ids(event_ids)
        videos = self.database.video_segments_by_ids(video_segment_ids)
        trip_ids.extend(row["trip_id"] for row in detections if row.get("trip_id"))
        trip_ids.extend(row["trip_id"] for row in videos if row.get("trip_id"))
        trip_ids = sorted(set(trip_ids))
        trips = self.database.trip_records(trip_ids)
        gps_points = self.database.gps_points_for_trips(trip_ids)

        payload = {
            "deviceId": self.config.sync.device_id or self.config.app.device_name,
            "uploadedAtUtc": _utc_now_text(),
            "trips": [_serialize_trip(row) for row in trips],
            "detections": [_serialize_detection(row) for row in detections],
            "gpsPoints": [_serialize_gps_point(row) for row in gps_points],
            "videoSegments": [_serialize_video_segment(row) for row in videos],
        }

        try:
            response = self._post_json("/ingest/batch", payload)
        except Exception as exc:
            self._mark_upload_failure(queue_ids, max((item["retry_count"] for item in metadata_items), default=0), str(exc))
            return {"ok": False, "message": str(exc)}

        self.database.mark_upload_items_state(queue_ids, "synced", last_error=None)
        for event_id in event_ids:
            self._advance_related_upload_state_after_metadata("detections", event_id)
        for video_segment_id in video_segment_ids:
            self._advance_related_upload_state_after_metadata("video_segments", video_segment_id)
        return {"ok": True, "response": response, "counts": {"items": len(metadata_items)}}

    def _post_json(self, path: str, payload: dict) -> dict:
        base_url = (self.config.sync.base_url or "").rstrip("/")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = request.Request(
            f"{base_url}{path}",
            data=body,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.config.sync.ingest_token}",
                "x-signomat-request-sha256": hashlib.sha256(body).hexdigest(),
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.sync.request_timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {"ok": True}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"sync HTTP {exc.code}: {detail or exc.reason}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"sync connection failed: {exc.reason}") from exc

    def _put_media(self, *, bucket: str, key: str, file_path: Path, content_type: str) -> dict:
        base_url = (self.config.sync.base_url or "").rstrip("/")
        target = f"{base_url}/ingest/media?{parse.urlencode({'bucket': bucket, 'key': key})}"
        parsed = parse.urlparse(target)
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        body_path = parsed.path
        if parsed.query:
            body_path = f"{body_path}?{parsed.query}"
        headers = {
            "content-type": content_type,
            "content-length": str(file_path.stat().st_size),
            "authorization": f"Bearer {self.config.sync.ingest_token}",
        }
        with file_path.open("rb") as handle:
            connection = connection_cls(parsed.netloc, timeout=self.config.sync.request_timeout_seconds)
            try:
                connection.request("PUT", body_path, body=handle, headers=headers)
                response = connection.getresponse()
                payload = response.read().decode("utf-8")
            finally:
                connection.close()
        if response.status >= 400:
            raise RuntimeError(f"media upload HTTP {response.status}: {payload or response.reason}")
        return json.loads(payload) if payload else {"ok": True}

    def _absolute_local_path(self, local_path: str) -> Path:
        candidate = Path(local_path)
        if candidate.is_absolute():
            return candidate
        return self.base_data_dir / candidate

    def _mark_upload_failure(self, queue_ids: list[str], retry_count: int, message: str) -> None:
        next_attempt_utc = _backoff_time_text(retry_count)
        self.database.mark_upload_items_state(
            queue_ids,
            "pending",
            last_error=message,
            next_attempt_utc=next_attempt_utc,
            increment_retry=True,
        )

    def _advance_related_upload_state_after_media(self, table_name: str, related_id: str) -> None:
        if table_name not in {"detections", "video_segments"}:
            return
        remaining_media = self.database.count_unsynced_related_uploads(
            table_name,
            related_id,
            item_types=("media_asset", "video_media"),
        )
        if remaining_media > 0:
            return
        current = self._current_upload_state(table_name, related_id)
        next_state = "synced" if current == "metadata_synced" else "media_synced"
        self.database.set_related_upload_state(table_name, related_id, next_state)

    def _advance_related_upload_state_after_metadata(self, table_name: str, related_id: str) -> None:
        if table_name not in {"detections", "video_segments"}:
            return
        remaining_media = self.database.count_unsynced_related_uploads(
            table_name,
            related_id,
            item_types=("media_asset", "video_media"),
        )
        next_state = "synced" if remaining_media == 0 else "metadata_synced"
        self.database.set_related_upload_state(table_name, related_id, next_state)

    def _current_upload_state(self, table_name: str, related_id: str) -> str | None:
        if table_name == "detections":
            row = self.database.detection_by_id(related_id)
        elif table_name == "video_segments":
            row = self.database.video_segment_by_id(related_id)
        else:
            return None
        return row.get("upload_state") if row else None


def _asset_pointer(local_path: str | None) -> dict | None:
    if not local_path:
        return None
    bucket = _bucket_name_for_path(local_path)
    return {"bucket": bucket, "key": local_path}


def _serialize_trip(row: dict) -> dict:
    return {
        "tripId": row["trip_id"],
        "startedAtUtc": row["started_at_utc"],
        "endedAtUtc": row["ended_at_utc"],
        "status": row["status"],
        "recordingEnabled": bool(row["recording_enabled"]),
        "inferenceEnabled": bool(row["inference_enabled"]),
        "notes": row["notes"],
    }


def _serialize_gps_point(row: dict) -> dict:
    return {
        "gpsPointId": row["gps_point_id"],
        "tripId": row["trip_id"],
        "timestampUtc": row["timestamp_utc"],
        "lat": row["lat"],
        "lon": row["lon"],
        "speed": row["speed"],
        "heading": row["heading"],
        "altitude": row["altitude"],
        "fixQuality": row["fix_quality"],
        "source": row["source"],
    }


def _serialize_video_segment(row: dict) -> dict:
    return {
        "videoSegmentId": row["video_segment_id"],
        "tripId": row["trip_id"],
        "startTimestampUtc": row["start_timestamp_utc"],
        "endTimestampUtc": row["end_timestamp_utc"],
        "media": _asset_pointer(row["file_path"]),
        "durationSec": row["duration_sec"],
        "fileSize": row["file_size"],
    }


def _serialize_detection(row: dict) -> dict:
    return {
        "eventId": row["event_id"],
        "tripId": row["trip_id"],
        "timestampUtc": row["timestamp_utc"],
        "categoryId": row["category_id"],
        "categoryLabel": row["category_label"],
        "specificLabel": row["specific_label"],
        "groupingMode": row["grouping_mode"],
        "rawDetectorLabel": row["raw_detector_label"],
        "rawClassifierLabel": row["raw_classifier_label"],
        "detectorConfidence": row["detector_confidence"],
        "classifierConfidence": row["classifier_confidence"],
        "gpsLat": row["gps_lat"],
        "gpsLon": row["gps_lon"],
        "gpsSpeed": row["gps_speed"],
        "heading": row["heading"],
        "bboxLeft": row["bbox_left"],
        "bboxTop": row["bbox_top"],
        "bboxRight": row["bbox_right"],
        "bboxBottom": row["bbox_bottom"],
        "annotatedFrame": _asset_pointer(row["annotated_frame_path"]),
        "cleanFrame": _asset_pointer(row["clean_frame_path"]),
        "signCrop": _asset_pointer(row["sign_crop_path"]),
        "annotatedThumbnail": _asset_pointer(row["annotated_thumbnail_path"]),
        "cleanThumbnail": _asset_pointer(row["clean_thumbnail_path"]),
        "signCropThumbnail": _asset_pointer(row["sign_crop_thumbnail_path"]),
        "videoSegmentId": row["video_segment_id"],
        "videoTimestampOffsetMs": row["video_timestamp_offset_ms"],
        "dedupeGroupId": row["dedupe_group_id"],
        "suppressedNearbyCount": row["suppressed_nearby_count"],
        "reviewState": row["review_state"],
        "notes": row["notes"],
    }


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bucket_name_for_path(local_path: str) -> str:
    return "thumbs" if "thumbnails/" in local_path else "media"


def _backoff_time_text(retry_count: int) -> str:
    seconds = min(300, max(5, 2 ** min(retry_count + 1, 8)))
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
