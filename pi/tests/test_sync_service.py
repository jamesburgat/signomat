from datetime import UTC, datetime, timedelta
from pathlib import Path

from signomat_pi.capture_service.service import CaptureService
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
    assert detection["upload_state"] == "synced"

    database.close()


def test_force_sync_uploads_media_assets_and_marks_detection_synced(tmp_path, monkeypatch):
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
    clean_path = base_dir / "trips" / "2026-03-30_trip_001" / "frames_clean" / "det_1.jpg"
    thumb_path = base_dir / "trips" / "2026-03-30_trip_001" / "thumbnails" / "clean" / "det_1.jpg"
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    clean_path.write_bytes(b"frame-bytes")
    thumb_path.write_bytes(b"thumb-bytes")
    (base_dir / "db").mkdir(parents=True, exist_ok=True)

    database = Database(base_dir / "db" / "signomat.db", migrations_dir)
    database.apply_migrations()

    trip_id = "2026-03-30_trip_001"
    database.create_trip(trip_id, True, True)
    database.stop_trip(trip_id)
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
            "annotated_frame_path": None,
            "clean_frame_path": "trips/2026-03-30_trip_001/frames_clean/det_1.jpg",
            "sign_crop_path": None,
            "annotated_thumbnail_path": None,
            "clean_thumbnail_path": "trips/2026-03-30_trip_001/thumbnails/clean/det_1.jpg",
            "sign_crop_thumbnail_path": None,
            "video_segment_id": None,
            "video_timestamp_offset_ms": None,
            "dedupe_group_id": "grp_1",
            "suppressed_nearby_count": 0,
            "upload_state": "pending",
            "review_state": "unreviewed",
            "notes": None,
        }
    )
    database.enqueue_upload("media_asset", "trips/2026-03-30_trip_001/frames_clean/det_1.jpg", "detections", "det_1", {"trip_id": trip_id})
    database.enqueue_upload("media_asset", "trips/2026-03-30_trip_001/thumbnails/clean/det_1.jpg", "detections", "det_1", {"trip_id": trip_id})
    database.enqueue_upload("detection_metadata", None, "detections", "det_1", {"trip_id": trip_id})

    service = SyncService(config, database)
    uploads: list[tuple[str, str, str]] = []

    def fake_put_media(*, bucket: str, key: str, file_path: Path, content_type: str) -> dict:
        uploads.append((bucket, key, content_type))
        assert file_path.exists()
        return {"ok": True}

    monkeypatch.setattr(service, "_put_media", fake_put_media)
    monkeypatch.setattr(service, "_post_json", lambda path, payload: {"ok": True, "receiptId": "receipt_media"})

    result = service.force_sync()

    assert result["ok"] is True
    assert ("media", "trips/2026-03-30_trip_001/frames_clean/det_1.jpg", "image/jpeg") in uploads
    assert ("thumbs", "trips/2026-03-30_trip_001/thumbnails/clean/det_1.jpg", "image/jpeg") in uploads
    detection = database.detection_by_id("det_1")
    assert detection is not None
    assert detection["upload_state"] == "synced"
    status = database.upload_status()
    assert status.get("synced") == 3

    database.close()


def test_force_sync_marks_transient_media_failures_as_deferred(tmp_path, monkeypatch):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")
    config.sync.enabled = True
    config.sync.base_url = "https://signomat-api.example.workers.dev"
    config.sync.ingest_token = "token"
    config.sync.device_id = "test-device"
    config.sync.batch_size = 1

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    source_migration = (Path(__file__).resolve().parents[1] / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    (migrations_dir / "0001_initial.sql").write_text(source_migration, encoding="utf-8")

    base_dir = tmp_path / "signomat-data"
    clean_path = base_dir / "trips" / "2026-03-30_trip_001" / "frames_clean" / "det_1.jpg"
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    clean_path.write_bytes(b"frame-bytes")
    (base_dir / "db").mkdir(parents=True, exist_ok=True)

    database = Database(base_dir / "db" / "signomat.db", migrations_dir)
    database.apply_migrations()

    trip_id = "2026-03-30_trip_001"
    database.create_trip(trip_id, True, True)
    database.stop_trip(trip_id)
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
            "annotated_frame_path": None,
            "clean_frame_path": "trips/2026-03-30_trip_001/frames_clean/det_1.jpg",
            "sign_crop_path": None,
            "annotated_thumbnail_path": None,
            "clean_thumbnail_path": None,
            "sign_crop_thumbnail_path": None,
            "video_segment_id": None,
            "video_timestamp_offset_ms": None,
            "dedupe_group_id": "grp_1",
            "suppressed_nearby_count": 0,
            "upload_state": "pending",
            "review_state": "unreviewed",
            "notes": None,
        }
    )
    database.enqueue_upload("media_asset", "trips/2026-03-30_trip_001/frames_clean/det_1.jpg", "detections", "det_1", {"trip_id": trip_id})

    service = SyncService(config, database)

    def fake_put_media(*, bucket: str, key: str, file_path: Path, content_type: str) -> dict:
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(service, "_put_media", fake_put_media)

    result = service.force_sync()

    assert result["ok"] is False
    assert service.last_result == "deferred"
    assert "Broken pipe" in (service.last_error or "")
    status = database.upload_status()
    assert status.get("pending") == 1

    database.close()


def test_force_sync_prioritizes_new_media_assets_before_old_video_retries(tmp_path, monkeypatch):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")
    config.sync.enabled = True
    config.sync.base_url = "https://signomat-api.example.workers.dev"
    config.sync.ingest_token = "token"
    config.sync.device_id = "test-device"
    config.sync.batch_size = 1

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    source_migration = (Path(__file__).resolve().parents[1] / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    (migrations_dir / "0001_initial.sql").write_text(source_migration, encoding="utf-8")

    base_dir = tmp_path / "signomat-data"
    old_video = base_dir / "trips" / "2026-03-30_trip_001" / "video" / "segment.mp4"
    new_frame = base_dir / "trips" / "2026-03-31_trip_001" / "frames_clean" / "det_1.jpg"
    old_video.parent.mkdir(parents=True, exist_ok=True)
    new_frame.parent.mkdir(parents=True, exist_ok=True)
    old_video.write_bytes(b"old-video")
    new_frame.write_bytes(b"new-frame")
    (base_dir / "db").mkdir(parents=True, exist_ok=True)

    database = Database(base_dir / "db" / "signomat.db", migrations_dir)
    database.apply_migrations()

    database.create_trip("2026-03-30_trip_001", True, True)
    database.stop_trip("2026-03-30_trip_001")
    database.execute(
        """
        INSERT INTO video_segments(
          video_segment_id, trip_id, start_timestamp_utc, end_timestamp_utc, file_path, file_size, duration_sec, upload_state
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("vid_old", "2026-03-30_trip_001", "2026-03-30T12:00:00Z", "2026-03-30T12:01:00Z", "trips/2026-03-30_trip_001/video/segment.mp4", 8, 60.0, "pending"),
    )
    old_queue = database.enqueue_upload(
        "video_media",
        "trips/2026-03-30_trip_001/video/segment.mp4",
        "video_segments",
        "vid_old",
        {"trip_id": "2026-03-30_trip_001"},
    )
    database.execute(
        "UPDATE upload_queue SET retry_count=5, created_at_utc='2026-03-30T12:02:00Z', updated_at_utc='2026-03-30T12:02:00Z' WHERE queue_id=?",
        (old_queue,),
    )

    trip_id = "2026-03-31_trip_001"
    database.create_trip(trip_id, True, True)
    database.stop_trip(trip_id)
    database.add_detection(
        {
            "event_id": "det_new",
            "trip_id": trip_id,
            "timestamp_utc": "2026-03-31T12:00:10Z",
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
            "annotated_frame_path": None,
            "clean_frame_path": "trips/2026-03-31_trip_001/frames_clean/det_1.jpg",
            "sign_crop_path": None,
            "annotated_thumbnail_path": None,
            "clean_thumbnail_path": None,
            "sign_crop_thumbnail_path": None,
            "video_segment_id": None,
            "video_timestamp_offset_ms": None,
            "dedupe_group_id": "grp_new",
            "suppressed_nearby_count": 0,
            "upload_state": "pending",
            "review_state": "unreviewed",
            "notes": None,
        }
    )
    database.enqueue_upload("media_asset", "trips/2026-03-31_trip_001/frames_clean/det_1.jpg", "detections", "det_new", {"trip_id": trip_id})

    service = SyncService(config, database)
    uploads: list[str] = []

    def fake_put_media(*, bucket: str, key: str, file_path: Path, content_type: str) -> dict:
        uploads.append(key)
        return {"ok": True}

    monkeypatch.setattr(service, "_put_media", fake_put_media)

    result = service.force_sync()

    assert result["ok"] is True
    assert uploads == ["trips/2026-03-31_trip_001/frames_clean/det_1.jpg"]
    remaining = database.pending_upload_items(limit=10, item_types=("video_media",))
    assert len(remaining) == 1
    assert remaining[0]["related_id"] == "vid_old"

    database.close()


def test_recover_interrupted_segments_finalizes_and_enqueues_missing_uploads(tmp_path):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    source_migration = (Path(__file__).resolve().parents[1] / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    (migrations_dir / "0001_initial.sql").write_text(source_migration, encoding="utf-8")

    base_dir = tmp_path / "signomat-data"
    trip_dir = base_dir / "trips" / "2026-03-30_trip_001" / "video"
    trip_dir.mkdir(parents=True, exist_ok=True)
    video_path = trip_dir / "segment_1.mp4"
    video_path.write_bytes(b"video-bytes")
    (base_dir / "db").mkdir(parents=True, exist_ok=True)

    database = Database(base_dir / "db" / "signomat.db", migrations_dir)
    database.apply_migrations()
    database.create_trip("2026-03-30_trip_001", True, True)

    future_start = (datetime.now(UTC) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    database.execute(
        "UPDATE trips SET started_at_utc=? WHERE trip_id=?",
        (future_start, "2026-03-30_trip_001"),
    )
    database.create_video_segment(
        {
            "video_segment_id": "segment_1",
            "trip_id": "2026-03-30_trip_001",
            "start_timestamp_utc": future_start,
            "file_path": "trips/2026-03-30_trip_001/video/segment_1.mp4",
        }
    )

    storage_config = load_config("pi/config/mock.yaml")
    storage_config.app.base_data_dir = str(base_dir)
    from signomat_pi.common.storage import StorageManager

    storage = StorageManager(storage_config)
    storage.initialize()
    capture = CaptureService(storage_config, storage, database)

    database.recover_interrupted_trips()
    recovered = capture.recover_interrupted_segments()

    trip = database.query_one("SELECT status, started_at_utc, ended_at_utc FROM trips WHERE trip_id=?", ("2026-03-30_trip_001",))
    segment = database.video_segment_by_id("segment_1")

    assert recovered == 1
    assert trip is not None
    assert trip["status"] == "interrupted"
    assert trip["ended_at_utc"] == future_start
    assert segment is not None
    assert segment["end_timestamp_utc"] == future_start
    assert segment["file_size"] == len(b"video-bytes")
    assert database.upload_item_exists("video_media", "video_segments", "segment_1") is True
    assert database.upload_item_exists("video_segment", "video_segments", "segment_1") is True

    capture.camera.stop()
    database.close()


def test_persist_detection_bundle_batches_detection_and_upload_rows(tmp_path):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    source_migration = (Path(__file__).resolve().parents[1] / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    (migrations_dir / "0001_initial.sql").write_text(source_migration, encoding="utf-8")

    base_dir = tmp_path / "signomat-data"
    (base_dir / "db").mkdir(parents=True, exist_ok=True)
    database = Database(base_dir / "db" / "signomat.db", migrations_dir)
    database.apply_migrations()

    trip_id = "2026-04-29_trip_001"
    database.create_trip(trip_id, True, True)
    database.stop_trip(trip_id)
    database.persist_detection_bundle(
        {
            "event_id": "det_bundle",
            "trip_id": trip_id,
            "timestamp_utc": "2026-04-29T12:00:10Z",
            "gps_lat": 41.0,
            "gps_lon": -71.0,
            "gps_speed": 10.5,
            "heading": 90.0,
            "category_id": "stop",
            "category_label": "stop",
            "specific_label": "stop",
            "grouping_mode": "specific",
            "raw_detector_label": "sign",
            "raw_classifier_label": "stop",
            "detector_confidence": 0.95,
            "classifier_confidence": 0.93,
            "bbox_left": 10,
            "bbox_top": 20,
            "bbox_right": 110,
            "bbox_bottom": 120,
            "annotated_frame_path": None,
            "clean_frame_path": "trips/2026-04-29_trip_001/frames_clean/det_bundle.jpg",
            "sign_crop_path": None,
            "annotated_thumbnail_path": None,
            "clean_thumbnail_path": "trips/2026-04-29_trip_001/thumbnails/clean/det_bundle.jpg",
            "sign_crop_thumbnail_path": None,
            "video_segment_id": None,
            "video_timestamp_offset_ms": None,
            "dedupe_group_id": "grp_bundle",
            "suppressed_nearby_count": 0,
            "upload_state": "pending",
            "review_state": "unreviewed",
            "notes": None,
        },
        [
            "trips/2026-04-29_trip_001/frames_clean/det_bundle.jpg",
            "trips/2026-04-29_trip_001/thumbnails/clean/det_bundle.jpg",
        ],
        metadata_payload={"trip_id": trip_id, "event_id": "det_bundle"},
    )

    detection = database.detection_by_id("det_bundle")
    queue_items = database.pending_upload_items(limit=10)

    assert detection is not None
    assert len(queue_items) == 3
    assert {item["item_type"] for item in queue_items} == {"media_asset", "detection_metadata"}

    database.close()
