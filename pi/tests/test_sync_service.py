from pathlib import Path

from signomat_pi.common.config import load_config
from signomat_pi.common.database import Database
from signomat_pi.sync_service.service import SyncService


def test_force_sync_batches_metadata_and_marks_queue_synced(tmp_path, monkeypatch):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")
    config.sync.enabled = True
    config.sync.base_url = "https://signomat-api.example.workers.dev"
    config.sync.ingest_token = "token"
    config.sync.device_id = "test-device"

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    source_migration = (Path(__file__).resolve().parents[1] / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    (migrations_dir / "0001_initial.sql").write_text(source_migration, encoding="utf-8")

    base_dir = tmp_path / "signomat-data"
    (base_dir / "db").mkdir(parents=True, exist_ok=True)
    database = Database(base_dir / "db" / "signomat.db", migrations_dir)
    database.apply_migrations()

    trip_id = "2026-03-30_trip_001"
    database.create_trip(trip_id, True, True)
    database.stop_trip(trip_id)
    database.enqueue_upload("trip_metadata", None, "trips", trip_id, {"trip_id": trip_id})

    database.execute(
        """
        INSERT INTO gps_points(
          gps_point_id, trip_id, timestamp_utc, lat, lon, speed, heading, altitude, fix_quality, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gps_1", trip_id, "2026-03-30T12:00:00Z", 41.0, -71.0, 10.5, 90.0, 5.0, "fix", "gpsd"),
    )

    database.execute(
        """
        INSERT INTO video_segments(
          video_segment_id, trip_id, start_timestamp_utc, end_timestamp_utc, file_path, file_size, duration_sec, upload_state
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("vid_1", trip_id, "2026-03-30T12:00:00Z", "2026-03-30T12:01:00Z", "trips/2026-03-30_trip_001/video/segment.mp4", 12345, 60.0, "pending"),
    )
    database.enqueue_upload("video_segment", "trips/2026-03-30_trip_001/video/segment.mp4", "video_segments", "vid_1", {"trip_id": trip_id})

    database.add_detection(
        {
            "event_id": "det_1",
            "trip_id": trip_id,
            "timestamp_utc": "2026-03-30T12:00:10Z",
            "gps_lat": 41.0,
            "gps_lon": -71.0,
            "gps_speed": 10.5,
            "heading": 90.0,
            "category_id": "stop",
            "category_label": "stop",
            "specific_label": "stop",
            "grouping_mode": "specific",
            "raw_detector_label": "red_octagon",
            "raw_classifier_label": "stop",
            "detector_confidence": 0.95,
            "classifier_confidence": 0.93,
            "bbox_left": 10,
            "bbox_top": 20,
            "bbox_right": 110,
            "bbox_bottom": 120,
            "annotated_frame_path": "trips/2026-03-30_trip_001/frames_annotated/det_1.jpg",
            "clean_frame_path": "trips/2026-03-30_trip_001/frames_clean/det_1.jpg",
            "sign_crop_path": "trips/2026-03-30_trip_001/crops/det_1.jpg",
            "annotated_thumbnail_path": "trips/2026-03-30_trip_001/thumbnails/annotated/det_1.jpg",
            "clean_thumbnail_path": "trips/2026-03-30_trip_001/thumbnails/clean/det_1.jpg",
            "sign_crop_thumbnail_path": "trips/2026-03-30_trip_001/thumbnails/crops/det_1.jpg",
            "video_segment_id": "vid_1",
            "video_timestamp_offset_ms": 10000,
            "dedupe_group_id": "grp_1",
            "suppressed_nearby_count": 0,
            "upload_state": "pending",
            "review_state": "unreviewed",
            "notes": None,
        }
    )
    database.enqueue_upload("detection_metadata", None, "detections", "det_1", {"trip_id": trip_id})

    service = SyncService(config, database)
    captured = {}

    def fake_post_json(path: str, payload: dict) -> dict:
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True, "receiptId": "receipt_test"}

    monkeypatch.setattr(service, "_post_json", fake_post_json)

    result = service.force_sync()

    assert result["ok"] is True
    assert captured["path"] == "/ingest/batch"
    assert captured["payload"]["deviceId"] == "test-device"
    assert len(captured["payload"]["trips"]) == 1
    assert len(captured["payload"]["gpsPoints"]) == 1
    assert len(captured["payload"]["videoSegments"]) == 1
    assert len(captured["payload"]["detections"]) == 1
    assert captured["payload"]["detections"][0]["annotatedThumbnail"]["bucket"] == "thumbs"
    assert captured["payload"]["videoSegments"][0]["media"]["bucket"] == "media"

    status = database.upload_status()
    assert status.get("synced") == 3

    detection = database.detection_by_id("det_1")
    assert detection is not None
    assert detection["upload_state"] == "metadata_synced"

    database.close()
