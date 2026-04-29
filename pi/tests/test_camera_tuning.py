import numpy as np

from signomat_pi.common.config import env_overrides
from signomat_pi.local_api.app import encode_preview_jpeg, resize_frame_for_preview


def test_env_overrides_include_camera_tuning(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_CAMERA_AUTO_EXPOSURE", "false")
    monkeypatch.setenv("SIGNOMAT_CAMERA_EXPOSURE_COMPENSATION", "1.25")
    monkeypatch.setenv("SIGNOMAT_CAMERA_BRIGHTNESS", "0.2")
    monkeypatch.setenv("SIGNOMAT_CAMERA_CONTRAST", "1.4")
    monkeypatch.setenv("SIGNOMAT_CAMERA_EXPOSURE_TIME_US", "12000")
    monkeypatch.setenv("SIGNOMAT_CAMERA_ANALOGUE_GAIN", "2.5")
    monkeypatch.setenv("SIGNOMAT_PREVIEW_MAX_WIDTH", "640")
    monkeypatch.setenv("SIGNOMAT_LOW_MEMORY_WARN_MB", "768")
    monkeypatch.setenv("SIGNOMAT_SAVE_CROPS", "true")
    monkeypatch.setenv("SIGNOMAT_MIN_BOX_AREA", "1600")

    overrides = env_overrides()

    assert "camera" not in overrides or "auto_exposure" not in overrides["camera"]
    assert "camera" not in overrides or "exposure_compensation" not in overrides["camera"]
    assert "camera" not in overrides or "brightness" not in overrides["camera"]
    assert "camera" not in overrides or "contrast" not in overrides["camera"]
    assert "camera" not in overrides or "exposure_time_us" not in overrides["camera"]
    assert "camera" not in overrides or "analogue_gain" not in overrides["camera"]
    assert overrides["api"]["preview_max_width"] == 640
    assert overrides["app"]["low_memory_warn_mb"] == 768
    assert overrides["inference"]["save_crops"] is True
    assert overrides["inference"]["min_box_area"] == 1600


def test_resize_frame_for_preview_downscales_width():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    resized = resize_frame_for_preview(frame, 640)

    assert resized.shape[:2] == (360, 640)


def test_resize_frame_for_preview_leaves_small_frame_alone():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    resized = resize_frame_for_preview(frame, 960)

    assert resized.shape == frame.shape


def test_encode_preview_jpeg_returns_jpeg_bytes():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    encoded = encode_preview_jpeg(frame, jpeg_quality=70, max_width=320)

    assert encoded is not None
    assert encoded[:2] == b"\xff\xd8"
