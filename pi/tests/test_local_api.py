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

        detections = client.get("/detections/recent")
        assert detections.status_code == 200
        assert len(detections.json()) >= 1

        gps = client.get("/gps/recent")
        assert gps.status_code == 200
        assert len(gps.json()) >= 1

        preview_page = client.get("/preview")
        assert preview_page.status_code == 200
        assert "Signomat live preview" in preview_page.text

        recordings_page = client.get("/recordings")
        assert recordings_page.status_code == 200
        assert "Trip Recordings" in recordings_page.text

        with client.stream("GET", "/preview.mjpg?max_frames=1") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
            first_chunk = next(response.iter_bytes())
            assert b"Content-Type: image/jpeg" in first_chunk

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
