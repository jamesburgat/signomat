from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import GPSPoint
from .utils import json_dumps, stable_id, utc_now_text


LOGGER = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path, migrations_dir: Path):
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self.lock:
            self.connection.execute("PRAGMA journal_mode=WAL;")
            self.connection.execute("PRAGMA foreign_keys=ON;")

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    def apply_migrations(self) -> None:
        migration_files = sorted(self.migrations_dir.glob("*.sql"))
        schema_table_exists = bool(
            self.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
        )
        if not schema_table_exists:
            applied_versions: set[str] = set()
        else:
            applied_versions = {row["version"] for row in self.query_all("SELECT version FROM schema_migrations")}

        for migration in migration_files:
            if migration.name in applied_versions:
                continue
            script = migration.read_text(encoding="utf-8")
            with self.lock:
                self.connection.executescript(script)
                self.connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                    (migration.name, utc_now_text()),
                )
                self.connection.commit()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.lock:
            self.connection.execute(sql, params)
            self.connection.commit()

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.lock:
            cursor = self.connection.execute(sql, params)
            return cursor.fetchone()

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            cursor = self.connection.execute(sql, params)
            return list(cursor.fetchall())

    def recover_interrupted_trips(self) -> None:
        self.execute(
            "UPDATE trips SET status='interrupted', ended_at_utc=? WHERE status='active'",
            (utc_now_text(),),
        )

    def create_trip(self, trip_id: str, recording_enabled: bool, inference_enabled: bool) -> None:
        self.execute(
            """
            INSERT INTO trips(trip_id, started_at_utc, status, recording_enabled, inference_enabled)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (trip_id, utc_now_text(), int(recording_enabled), int(inference_enabled)),
        )

    def stop_trip(self, trip_id: str) -> None:
        self.execute(
            "UPDATE trips SET status='stopped', ended_at_utc=? WHERE trip_id=?",
            (utc_now_text(), trip_id),
        )

    def active_trip(self) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM trips WHERE status='active' ORDER BY started_at_utc DESC LIMIT 1")

    def next_trip_sequence(self, day_prefix: str) -> int:
        row = self.query_one("SELECT COUNT(*) AS count FROM trips WHERE trip_id LIKE ?", (f"{day_prefix}_trip_%",))
        return int(row["count"]) + 1 if row else 1

    def add_gps_point(self, trip_id: str, point: GPSPoint) -> str:
        gps_point_id = stable_id("gps")
        self.execute(
            """
            INSERT INTO gps_points(
              gps_point_id, trip_id, timestamp_utc, lat, lon, speed, heading, altitude, fix_quality, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gps_point_id,
                trip_id,
                point.timestamp_utc,
                point.lat,
                point.lon,
                point.speed,
                point.heading,
                point.altitude,
                point.fix_quality,
                point.source,
            ),
        )
        return gps_point_id

    def latest_gps_point(self, trip_id: str | None = None) -> sqlite3.Row | None:
        if trip_id:
            return self.query_one(
                "SELECT * FROM gps_points WHERE trip_id=? ORDER BY timestamp_utc DESC LIMIT 1",
                (trip_id,),
            )
        return self.query_one("SELECT * FROM gps_points ORDER BY timestamp_utc DESC LIMIT 1")

    def create_video_segment(self, segment: dict[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO video_segments(
              video_segment_id, trip_id, start_timestamp_utc, file_path, upload_state
            ) VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                segment["video_segment_id"],
                segment["trip_id"],
                segment["start_timestamp_utc"],
                segment["file_path"],
            ),
        )

    def finalize_video_segment(self, segment_id: str, end_timestamp_utc: str, file_size: int, duration_sec: float) -> None:
        self.execute(
            """
            UPDATE video_segments
            SET end_timestamp_utc=?, file_size=?, duration_sec=?
            WHERE video_segment_id=?
            """,
            (end_timestamp_utc, file_size, duration_sec, segment_id),
        )

    def add_detection(self, payload: dict[str, Any]) -> None:
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["?"] * len(payload))
        self.execute(
            f"INSERT INTO detections({columns}) VALUES ({placeholders})",
            tuple(payload.values()),
        )

    def increment_suppressed_count(self, event_id: str) -> None:
        self.execute(
            "UPDATE detections SET suppressed_nearby_count = suppressed_nearby_count + 1 WHERE event_id=?",
            (event_id,),
        )

    def enqueue_upload(
        self,
        item_type: str,
        local_path: str | None,
        related_table: str,
        related_id: str,
        payload: dict[str, Any],
    ) -> str:
        queue_id = stable_id("queue")
        now = utc_now_text()
        self.execute(
            """
            INSERT INTO upload_queue(
              queue_id, item_type, local_path, related_table, related_id, payload_json,
              state, retry_count, next_attempt_utc, last_error, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, ?, ?)
            """,
            (queue_id, item_type, local_path, related_table, related_id, json_dumps(payload), now, now),
        )
        return queue_id

    def add_device_event(self, event_type: str, severity: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.execute(
            """
            INSERT INTO device_events(device_event_id, timestamp_utc, event_type, severity, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (stable_id("dev"), utc_now_text(), event_type, severity, message, json_dumps(details or {})),
        )

    def upsert_setting(self, key: str, value: Any) -> None:
        self.execute(
            """
            INSERT INTO settings(key, value_json, updated_at_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at_utc=excluded.updated_at_utc
            """,
            (key, json.dumps(value), utc_now_text()),
        )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value_json FROM settings WHERE key=?", (key,))
        if not row:
            return default
        return json.loads(row["value_json"])

    def replace_taxonomy_snapshot(self, version: str, entries: list[dict[str, Any]]) -> None:
        with self.lock:
            self.connection.execute("DELETE FROM taxonomy_mapping")
            for entry in entries:
                self.connection.execute(
                    """
                    INSERT INTO taxonomy_mapping(
                      mapping_id, raw_label, category_id, category_label, specific_label, grouping_mode,
                      source_config_version, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_id("map"),
                        entry["raw_label"],
                        entry["category_id"],
                        entry["category_label"],
                        entry.get("specific_label"),
                        entry["grouping_mode"],
                        version,
                        utc_now_text(),
                    ),
                )
            self.connection.commit()

    def replace_model_versions(self, items: list[tuple[str, str, str]]) -> None:
        with self.lock:
            self.connection.execute("DELETE FROM model_versions")
            for component, version_label, source in items:
                self.connection.execute(
                    """
                    INSERT INTO model_versions(model_version_id, component, version_label, source, active, created_at_utc)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (stable_id("model"), component, version_label, source, utc_now_text()),
                )
            self.connection.commit()

    def recent_detections(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in self.query_all("SELECT * FROM detections ORDER BY timestamp_utc DESC LIMIT ?", (limit,))]

    def detection_by_id(self, event_id: str) -> dict[str, Any] | None:
        row = self.query_one("SELECT * FROM detections WHERE event_id=?", (event_id,))
        return dict(row) if row else None

    def detections_for_trip(self, trip_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.query_all(
                "SELECT * FROM detections WHERE trip_id=? ORDER BY timestamp_utc ASC",
                (trip_id,),
            )
        ]

    def recent_gps_points(self, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(row) for row in self.query_all("SELECT * FROM gps_points ORDER BY timestamp_utc DESC LIMIT ?", (limit,))]

    def recent_video_segments(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in self.query_all("SELECT * FROM video_segments ORDER BY start_timestamp_utc DESC LIMIT ?", (limit,))]

    def video_segments_for_trip(self, trip_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.query_all(
                "SELECT * FROM video_segments WHERE trip_id=? ORDER BY start_timestamp_utc DESC",
                (trip_id,),
            )
        ]

    def video_segment_by_id(self, segment_id: str) -> dict[str, Any] | None:
        row = self.query_one("SELECT * FROM video_segments WHERE video_segment_id=?", (segment_id,))
        return dict(row) if row else None

    def recent_trips(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in self.query_all("SELECT * FROM trips ORDER BY started_at_utc DESC LIMIT ?", (limit,))]

    def detection_count_for_trip(self, trip_id: str) -> int:
        row = self.query_one("SELECT COUNT(*) AS count FROM detections WHERE trip_id=?", (trip_id,))
        return int(row["count"]) if row else 0

    def detection_category_counts_for_trip(self, trip_id: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            """
            SELECT category_label, COUNT(*) AS count, MAX(timestamp_utc) AS last_seen_at
            FROM detections
            WHERE trip_id=?
            GROUP BY category_label
            ORDER BY count DESC, category_label ASC
            """,
            (trip_id,),
        )
        return [dict(row) for row in rows]

    def upload_status(self) -> dict[str, int]:
        rows = self.query_all("SELECT state, COUNT(*) AS count FROM upload_queue GROUP BY state")
        summary = {row["state"]: row["count"] for row in rows}
        summary["total"] = sum(summary.values())
        return summary

    def pending_upload_items(self, limit: int = 100, item_types: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM upload_queue WHERE state='pending' AND (next_attempt_utc IS NULL OR next_attempt_utc <= ?)"
        params: list[Any] = [utc_now_text()]
        if item_types:
            placeholders = ", ".join(["?"] * len(item_types))
            sql += f" AND item_type IN ({placeholders})"
            params.extend(item_types)
        sql += " ORDER BY created_at_utc ASC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.query_all(sql, tuple(params))]

    def mark_upload_items_state(
        self,
        queue_ids: list[str],
        state: str,
        *,
        last_error: str | None = None,
        next_attempt_utc: str | None = None,
        increment_retry: bool = False,
    ) -> None:
        if not queue_ids:
            return
        placeholders = ", ".join(["?"] * len(queue_ids))
        retry_expr = "retry_count + 1" if increment_retry else "retry_count"
        params: list[Any] = [state, last_error, next_attempt_utc, utc_now_text(), *queue_ids]
        self.execute(
            f"""
            UPDATE upload_queue
            SET state=?,
                last_error=?,
                next_attempt_utc=?,
                retry_count={retry_expr},
                updated_at_utc=?
            WHERE queue_id IN ({placeholders})
            """,
            tuple(params),
        )

    def mark_related_upload_state(self, table_name: str, ids: list[str], upload_state: str) -> None:
        if not ids:
            return
        if table_name == "detections":
            id_column = "event_id"
        elif table_name == "video_segments":
            id_column = "video_segment_id"
        else:
            return
        placeholders = ", ".join(["?"] * len(ids))
        self.execute(
            f"UPDATE {table_name} SET upload_state=? WHERE {id_column} IN ({placeholders})",
            (upload_state, *ids),
        )

    def set_related_upload_state(self, table_name: str, related_id: str, upload_state: str) -> None:
        if table_name == "detections":
            id_column = "event_id"
        elif table_name == "video_segments":
            id_column = "video_segment_id"
        else:
            return
        self.execute(
            f"UPDATE {table_name} SET upload_state=? WHERE {id_column}=?",
            (upload_state, related_id),
        )

    def count_unsynced_related_uploads(
        self,
        related_table: str,
        related_id: str,
        *,
        item_types: tuple[str, ...] | None = None,
    ) -> int:
        sql = "SELECT COUNT(*) AS count FROM upload_queue WHERE related_table=? AND related_id=? AND state != 'synced'"
        params: list[Any] = [related_table, related_id]
        if item_types:
            placeholders = ", ".join(["?"] * len(item_types))
            sql += f" AND item_type IN ({placeholders})"
            params.extend(item_types)
        row = self.query_one(sql, tuple(params))
        return int(row["count"]) if row else 0

    def trip_records(self, trip_ids: list[str]) -> list[dict[str, Any]]:
        if not trip_ids:
            return []
        placeholders = ", ".join(["?"] * len(trip_ids))
        return [dict(row) for row in self.query_all(f"SELECT * FROM trips WHERE trip_id IN ({placeholders})", tuple(trip_ids))]

    def gps_points_for_trips(self, trip_ids: list[str]) -> list[dict[str, Any]]:
        if not trip_ids:
            return []
        placeholders = ", ".join(["?"] * len(trip_ids))
        return [
            dict(row)
            for row in self.query_all(
                f"SELECT * FROM gps_points WHERE trip_id IN ({placeholders}) ORDER BY timestamp_utc ASC",
                tuple(trip_ids),
            )
        ]

    def video_segments_by_ids(self, segment_ids: list[str]) -> list[dict[str, Any]]:
        if not segment_ids:
            return []
        placeholders = ", ".join(["?"] * len(segment_ids))
        return [
            dict(row)
            for row in self.query_all(
                f"SELECT * FROM video_segments WHERE video_segment_id IN ({placeholders})",
                tuple(segment_ids),
            )
        ]

    def detections_by_ids(self, event_ids: list[str]) -> list[dict[str, Any]]:
        if not event_ids:
            return []
        placeholders = ", ".join(["?"] * len(event_ids))
        return [dict(row) for row in self.query_all(f"SELECT * FROM detections WHERE event_id IN ({placeholders})", tuple(event_ids))]

    def recent_device_events(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in self.query_all("SELECT * FROM device_events ORDER BY timestamp_utc DESC LIMIT ?", (limit,))]
