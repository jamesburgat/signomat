import numpy as np

from signomat_pi.common.config import env_overrides
from signomat_pi.local_api.app import resize_frame_for_preview


def test_env_overrides_include_camera_tuning(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_CAMERA_AUTO_EXPOSURE", "false")
    monkeypatch.setenv("SIGNOMAT_CAMERA_EXPOSURE_COMPENSATION", "1.25")
    monkeypatch.setenv("SIGNOMAT_CAMERA_BRIGHTNESS", "0.2")
    monkeypatch.setenv("SIGNOMAT_CAMERA_CONTRAST", "1.4")
    monkeypatch.setenv("SIGNOMAT_CAMERA_EXPOSURE_TIME_US", "12000")
    monkeypatch.setenv("SIGNOMAT_CAMERA_ANALOGUE_GAIN", "2.5")
    monkeypatch.setenv("SIGNOMAT_PREVIEW_MAX_WIDTH", "640")

    overrides = env_overrides()

    assert overrides["camera"]["auto_exposure"] is False
    assert overrides["camera"]["exposure_compensation"] == 1.25
    assert overrides["camera"]["brightness"] == 0.2
    assert overrides["camera"]["contrast"] == 1.4
    assert overrides["camera"]["exposure_time_us"] == 12000
    assert overrides["camera"]["analogue_gain"] == 2.5
    assert overrides["api"]["preview_max_width"] == 640


def test_resize_frame_for_preview_downscales_width():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    resized = resize_frame_for_preview(frame, 640)

    assert resized.shape[:2] == (360, 640)


def test_resize_frame_for_preview_leaves_small_frame_alone():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    resized = resize_frame_for_preview(frame, 960)

    assert resized.shape == frame.shape
