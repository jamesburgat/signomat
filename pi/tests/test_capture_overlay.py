from datetime import UTC, datetime
import threading
from types import SimpleNamespace

import numpy as np

from signomat_pi.capture_service.service import CaptureService


def test_capture_overlay_scales_and_draws_box():
    capture = CaptureService.__new__(CaptureService)
    capture.config = SimpleNamespace(camera=SimpleNamespace(overlay_hold_seconds=2.5, annotate_recording=True))
    capture.overlays = []
    capture.state_lock = threading.Lock()

    seen_at = datetime.now(UTC)
    capture.note_detection_overlay(
        "stop",
        (10, 10, 50, 50),
        0.91,
        original_shape=(720, 1280, 3),
        processed_shape=(360, 640, 3),
        seen_at=seen_at,
    )

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    annotated = capture._annotate_frame(frame, seen_at)

    assert annotated.shape == frame.shape
    assert int(annotated.sum()) > 0
    assert len(capture.overlays) == 1
