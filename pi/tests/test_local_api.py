import time

from fastapi.testclient import TestClient

from signomat_pi.common.config import load_config
from signomat_pi.common.runtime import SignomatRuntime
from signomat_pi.local_api.app import create_app


def test_mock_runtime_emits_status_and_detections(tmp_path):
    config = load_config("pi/config/mock.yaml")
    config.app.base_data_dir = str(tmp_path / "signomat-data")
    runtime = SignomatRuntime(config)
    app = create_app(runtime)
    client = TestClient(app)

    runtime.start()
    try:
        response = client.post("/session/start")
        assert response.status_code == 200
        trip_id = response.json()["trip_id"]
        assert trip_id

        time.sleep(2.5)

        status = client.get("/status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["trip_active"] is True
        assert payload["detection_count_trip"] >= 1

        ble_payloads = client.get("/ble/payloads")
        assert ble_payloads.status_code == 200
        ble = ble_payloads.json()
        assert "7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000" in ble
        assert ble["7b1e1002-5d1f-4aa0-9a7d-6f5c0b6c1000"]["trip"] is True
        assert "gps" in ble["7b1e1007-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "cats" in ble["7b1e1004-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "recent" in ble["7b1e1004-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "preview_base_url" in ble["7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000"]
        assert "preview_fallback_base_url" in ble["7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000"]

        detections = client.get("/detections/recent")
        assert detections.status_code == 200
        assert len(detections.json()) >= 1

        replay = client.post(f"/replay/{trip_id}")
        assert replay.status_code == 200
        replay_payload = replay.json()
        assert replay_payload["ok"] is True
        assert replay_payload["trip_id"] == trip_id
        assert replay_payload["evaluated_detections"] >= 1
        assert replay_payload["mode"] == "stored_detection_frame_replay"
        assert replay_payload.get("export_path")

        gps = client.get("/gps/recent")
        assert gps.status_code == 200
        assert len(gps.json()) >= 1

        preview_page = client.get("/preview")
        assert preview_page.status_code == 200
        assert "Signomat live preview" in preview_page.text
        assert "Camera Tuning" in preview_page.text

        tuning = client.get("/camera/tuning")
        assert tuning.status_code == 200
        assert tuning.json()["tuning"]["backend"] == "mock"

        tuning_update = client.post(
            "/camera/tuning",
            json={
                "auto_exposure": False,
                "exposure_time_us": 18000,
                "analogue_gain": 8.0,
                "brightness": 0.12,
                "contrast": 1.18,
            },
        )
        assert tuning_update.status_code == 200
        updated = tuning_update.json()["tuning"]
        assert updated["auto_exposure"] is False
        assert updated["exposure_time_us"] == 18000
        assert updated["analogue_gain"] == 8.0

        recordings_page = client.get("/recordings")
        assert recordings_page.status_code == 200
        assert "Trip Recordings" in recordings_page.text

        with client.stream("GET", "/preview.mjpg?max_frames=1") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
            first_chunk = next(response.iter_bytes())
            assert b"Content-Type: image/jpeg" in first_chunk

        preview_still = client.get("/preview.jpg")
        assert preview_still.status_code == 200
        assert preview_still.headers["content-type"].startswith("image/jpeg")
        assert preview_still.content[:2] == b"\xff\xd8"

        recent_videos = client.get("/video/recent").json()
        assert recent_videos
        trip_id = recent_videos[0]["trip_id"]
        segment_id = recent_videos[0]["video_segment_id"]

        trip_recordings = client.get(f"/recordings/{trip_id}")
        assert trip_recordings.status_code == 200
        assert trip_id in trip_recordings.text
        assert "Play Full Trip" in trip_recordings.text

        video_file = client.get(f"/recordings/video/{segment_id}")
        assert video_file.status_code == 200
        assert video_file.headers["content-type"].startswith("video/mp4")
    finally:
        runtime.stop()
