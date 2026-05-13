import time

from signomat_pi.common.config import load_config
from signomat_pi.common.runtime import SignomatRuntime
from signomat_pi.local_api.app import CameraTuningUpdate, create_app


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"endpoint not found: {method} {path}")


def test_mock_runtime_emits_status_and_detections(tmp_path):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")
    runtime = SignomatRuntime(config)
    app = create_app(runtime)

    runtime.start()
    try:
        trip_id = _endpoint(app, "/session/start", "POST")()["trip_id"]
        assert trip_id

        time.sleep(2.5)

        payload = _endpoint(app, "/status")()
        assert payload["trip_active"] is True
        assert payload["detection_count_trip"] >= 1
        assert payload["sync_auto_enabled"] is True
        assert payload["classification_auto_enabled"] is True

        ble = _endpoint(app, "/ble/payloads")()
        assert "7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000" in ble
        assert ble["7b1e1002-5d1f-4aa0-9a7d-6f5c0b6c1000"]["trip"] is True
        assert "gps" in ble["7b1e1007-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "cats" in ble["7b1e1004-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "recent" in ble["7b1e1004-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "preview_base_url" in ble["7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "preview_fallback_base_url" in ble["7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000"]

        detections = _endpoint(app, "/detections/recent")(20)
        assert len(detections) >= 1

        replay_payload = _endpoint(app, "/replay/{trip_id}", "POST")(trip_id)
        assert replay_payload["ok"] is True
        assert replay_payload["trip_id"] == trip_id
        assert replay_payload["evaluated_detections"] >= 1
        assert replay_payload["mode"] == "stored_detection_frame_replay"
        assert replay_payload.get("export_path")

        classification_status = _endpoint(app, "/classification/status")()
        assert "pending_trips" in classification_status

        gps = _endpoint(app, "/gps/recent")(50)
        assert len(gps) >= 1

        preview_page = _endpoint(app, "/preview")()
        assert "Signomat live preview" in preview_page
        assert "Camera Exposure Audit" in preview_page
        assert "Post-Trip Classification" in preview_page
        assert "Day" not in preview_page
        assert "Night" not in preview_page

        tuning = _endpoint(app, "/camera/tuning")()
        assert tuning["tuning"]["backend"] == "mock"
        assert tuning["supported"] is False

        tuning_update = _endpoint(app, "/camera/tuning", "POST")(
            CameraTuningUpdate(
                auto_exposure=False,
                exposure_time_us=18000,
                analogue_gain=8.0,
                brightness=0.12,
                contrast=1.18,
            )
        )
        updated = tuning_update
        assert updated["ok"] is False
        assert updated["supported"] is False
        assert "disabled" in updated["message"]

        recordings_page = _endpoint(app, "/recordings")()
        assert "Trip Recordings" in recordings_page

        preview_stream = _endpoint(app, "/preview.mjpg")(max_frames=1)
        assert preview_stream.media_type.startswith("multipart/x-mixed-replace")

        preview_still = _endpoint(app, "/preview.jpg")()
        assert preview_still.media_type.startswith("image/jpeg")
        assert preview_still.body[:2] == b"\xff\xd8"

        recent_videos = _endpoint(app, "/video/recent")(20)
        assert recent_videos
        trip_id = recent_videos[0]["trip_id"]
        segment_id = recent_videos[0]["video_segment_id"]

        trip_recordings = _endpoint(app, "/recordings/{trip_id}")(trip_id)
        assert trip_id in trip_recordings
        assert "Play Full Trip" in trip_recordings

        video_file = _endpoint(app, "/recordings/video/{segment_id}")(segment_id)
        assert video_file.media_type.startswith("video/mp4")

        stop_payload = _endpoint(app, "/session/stop", "POST")()
        stopped_trip_id = stop_payload["trip_id"]
        assert stopped_trip_id == trip_id
        assert stop_payload["classification_queued"] is True
        assert stop_payload["classification_status"]["queued_trip_ids"] or stop_payload["classification_status"]["running"]

        deadline = time.time() + 10
        final_status = None
        while time.time() < deadline:
            final_status = _endpoint(app, "/classification/status")()
            if final_status["last_completed_trip_id"] == trip_id:
                break
            time.sleep(0.25)
        assert final_status is not None
        assert final_status["last_completed_trip_id"] == trip_id

        run_again = _endpoint(app, "/classification/run", "POST")()
        assert run_again["ok"] in {True, False}

        sync_pause = _endpoint(app, "/sync/auto/pause", "POST")()
        assert sync_pause["auto_enabled"] is False
        sync_resume = _endpoint(app, "/sync/auto/resume", "POST")()
        assert sync_resume["auto_enabled"] is True

        class_pause = _endpoint(app, "/classification/auto/pause", "POST")()
        assert class_pause["auto_enabled"] is False

        trip_id = _endpoint(app, "/session/start", "POST")()["trip_id"]
        assert trip_id
        time.sleep(2.5)
        stop_payload = _endpoint(app, "/session/stop", "POST")()
        assert stop_payload["trip_id"] == trip_id
        assert stop_payload["classification_queued"] is False

        paused_status = _endpoint(app, "/classification/status")()
        assert paused_status["auto_enabled"] is False

        class_resume = _endpoint(app, "/classification/auto/resume", "POST")()
        assert class_resume["auto_enabled"] is True
    finally:
        runtime.stop()
