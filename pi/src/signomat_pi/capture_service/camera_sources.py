from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from signomat_pi.common.config import SignomatConfig

try:
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover
    Picamera2 = None


class CameraError(RuntimeError):
    pass


class CameraSource(Protocol):
    def start(self) -> None: ...
    def capture_frame(self) -> np.ndarray: ...
    def stop(self) -> None: ...
    def describe(self) -> str: ...


@dataclass
class Picamera2CameraSource:
    camera_index: int | None
    width: int
    height: int
    warmup_seconds: float

    def __post_init__(self) -> None:
        self.camera = None

    def start(self) -> None:
        if Picamera2 is None:
            raise CameraError("Picamera2 is not installed")
        kwargs = {"camera_num": self.camera_index} if self.camera_index is not None else {}
        self.camera = Picamera2(**kwargs)
        config = self.camera.create_preview_configuration(main={"size": (self.width, self.height)})
        self.camera.configure(config)
        self.camera.start()
        time.sleep(self.warmup_seconds)

    def capture_frame(self) -> np.ndarray:
        if self.camera is None:
            raise CameraError("Picamera2 camera is not started")
        frame = self.camera.capture_array()
        if frame is None:
            raise CameraError("Picamera2 returned an empty frame")
        if len(frame.shape) == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        channels = frame.shape[2]
        if channels == 4:
            return cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def stop(self) -> None:
        if self.camera is None:
            return
        try:
            self.camera.stop()
        finally:
            self.camera = None

    def describe(self) -> str:
        target = "default" if self.camera_index is None else str(self.camera_index)
        return f"picamera2:{target} {self.width}x{self.height}"


@dataclass
class OpenCVCameraSource:
    device: str | int | None
    width: int
    height: int
    fps: int
    fourcc: str | None
    warmup_seconds: float

    def __post_init__(self) -> None:
        self.capture = None
        self.active_target: str | int | None = None
        self.scan_note: str | None = None

    @staticmethod
    def _video_node_index(path: Path) -> int | None:
        match = re.fullmatch(r"video(\d+)", path.name)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _normalize_target(target: str | int) -> str | int:
        if isinstance(target, int):
            return target
        text = str(target).strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        return text

    def _candidate_targets(self):
        if self.device is not None:
            yield self._normalize_target(self.device)
            return

        video_paths = sorted(
            Path("/dev").glob("video*"),
            key=lambda path: (self._video_node_index(path) is None, self._video_node_index(path) or 0),
        )
        video_nodes: list[str] = []
        helper_nodes: list[str] = []
        for path in video_paths:
            index = self._video_node_index(path)
            if index is None:
                continue
            if index < 10:
                video_nodes.append(str(path))
            else:
                helper_nodes.append(path.name)

        if video_nodes:
            for path in video_nodes:
                yield path
            return

        if helper_nodes:
            sample = ", ".join(helper_nodes[:4])
            extra = "" if len(helper_nodes) <= 4 else ", ..."
            self.scan_note = f"found only helper video nodes ({sample}{extra})"
            return

        for index in range(4):
            yield index

    def _open_target(self, target: str | int):
        capture = cv2.VideoCapture(target, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            return None

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        if self.fourcc:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc[:4].ljust(4)))
        return capture

    def start(self) -> None:
        errors: list[str] = []
        self.scan_note = None
        for target in self._candidate_targets():
            capture = self._open_target(target)
            if capture is None:
                errors.append(f"{target}: open failed")
                continue

            ok, frame = capture.read()
            if not ok or frame is None:
                errors.append(f"{target}: no frames")
                capture.release()
                continue

            self.capture = capture
            self.active_target = target
            time.sleep(self.warmup_seconds)
            return

        detail = ", ".join(errors) if errors else self.scan_note or "no candidate devices"
        raise CameraError(f"OpenCV camera start failed ({detail})")

    def capture_frame(self) -> np.ndarray:
        if self.capture is None:
            raise CameraError("OpenCV camera is not started")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise CameraError(f"OpenCV failed to read from {self.active_target}")
        return frame

    def stop(self) -> None:
        if self.capture is None:
            return
        try:
            self.capture.release()
        finally:
            self.capture = None

    def describe(self) -> str:
        return f"opencv:{self.active_target} {self.width}x{self.height}"


class MockCameraSource:
    def __init__(self, width: int, height: int, fps: int, text_overlay: bool = True):
        self.width = width
        self.height = height
        self.fps = fps
        self.text_overlay = text_overlay
        self.frame_index = 0

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def describe(self) -> str:
        return "mock-camera"

    def capture_frame(self) -> np.ndarray:
        self.frame_index += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (70, 70, 70)
        cv2.rectangle(frame, (0, int(self.height * 0.62)), (self.width, self.height), (60, 60, 60), -1)
        cv2.line(frame, (self.width // 2, self.height), (self.width // 2, int(self.height * 0.62)), (255, 255, 255), 5)
        cv2.line(frame, (self.width // 2 - 180, self.height), (self.width // 2 - 90, int(self.height * 0.62)), (0, 255, 255), 4)
        sign_type = self.frame_index % 5
        center_x = int(self.width * 0.78)
        center_y = int(self.height * (0.25 + 0.05 * math.sin(self.frame_index / 10)))
        if sign_type == 0:
            self._draw_stop(frame, center_x, center_y)
        elif sign_type == 1:
            self._draw_speed_limit(frame, center_x, center_y, "35")
        elif sign_type == 2:
            self._draw_yield(frame, center_x, center_y)
        elif sign_type == 3:
            self._draw_warning(frame, center_x, center_y)
        else:
            self._draw_mandatory(frame, center_x, center_y)
        if self.text_overlay:
            cv2.putText(frame, "SIGNOMAT MOCK", (32, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        time.sleep(1 / max(self.fps, 1))
        return frame

    def _draw_stop(self, frame: np.ndarray, cx: int, cy: int) -> None:
        radius = 65
        points = []
        for i in range(8):
            angle = math.radians(22.5 + i * 45)
            points.append((int(cx + radius * math.cos(angle)), int(cy + radius * math.sin(angle))))
        cv2.fillPoly(frame, [np.array(points, dtype=np.int32)], (0, 0, 255))
        cv2.putText(frame, "STOP", (cx - 42, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    def _draw_speed_limit(self, frame: np.ndarray, cx: int, cy: int, value: str) -> None:
        cv2.circle(frame, (cx, cy), 72, (0, 0, 255), thickness=10)
        cv2.circle(frame, (cx, cy), 58, (255, 255, 255), thickness=-1)
        cv2.putText(frame, value, (cx - 32, cy + 18), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)

    def _draw_yield(self, frame: np.ndarray, cx: int, cy: int) -> None:
        triangle = np.array([(cx, cy - 72), (cx - 72, cy + 56), (cx + 72, cy + 56)], dtype=np.int32)
        cv2.fillPoly(frame, [triangle], (0, 0, 255))
        inner = np.array([(cx, cy - 48), (cx - 46, cy + 34), (cx + 46, cy + 34)], dtype=np.int32)
        cv2.fillPoly(frame, [inner], (255, 255, 255))

    def _draw_warning(self, frame: np.ndarray, cx: int, cy: int) -> None:
        diamond = np.array([(cx, cy - 74), (cx - 74, cy), (cx, cy + 74), (cx + 74, cy)], dtype=np.int32)
        cv2.fillPoly(frame, [diamond], (0, 255, 255))
        cv2.line(frame, (cx - 20, cy - 20), (cx + 20, cy + 20), (0, 0, 0), 4)
        cv2.line(frame, (cx + 20, cy - 20), (cx - 20, cy + 20), (0, 0, 0), 4)

    def _draw_mandatory(self, frame: np.ndarray, cx: int, cy: int) -> None:
        cv2.circle(frame, (cx, cy), 68, (255, 0, 0), thickness=-1)
        cv2.arrowedLine(frame, (cx - 24, cy + 24), (cx + 24, cy - 24), (255, 255, 255), 5, tipLength=0.4)


def _picamera_is_available() -> bool:
    if Picamera2 is None:
        return False
    try:
        return bool(Picamera2.global_camera_info())
    except Exception:
        return False


def create_camera_source(config: SignomatConfig) -> CameraSource:
    backend = config.camera.backend.lower()
    if config.mock.enabled or backend == "mock":
        return MockCameraSource(
            width=config.camera.width,
            height=config.camera.height,
            fps=config.camera.fps,
            text_overlay=config.mock.frame_text_overlay,
        )

    if backend not in {"auto", "picamera2", "opencv"}:
        raise CameraError(f"Unsupported camera backend '{backend}'")

    if backend == "picamera2":
        return Picamera2CameraSource(
            camera_index=config.camera.index,
            width=config.camera.width,
            height=config.camera.height,
            warmup_seconds=config.camera.warmup_seconds,
        )

    target = config.camera.device if config.camera.device is not None else config.camera.index
    if backend == "opencv":
        return OpenCVCameraSource(
            device=target,
            width=config.camera.width,
            height=config.camera.height,
            fps=config.camera.fps,
            fourcc=config.camera.fourcc,
            warmup_seconds=config.camera.warmup_seconds,
        )

    if _picamera_is_available():
        return Picamera2CameraSource(
            camera_index=config.camera.index,
            width=config.camera.width,
            height=config.camera.height,
            warmup_seconds=config.camera.warmup_seconds,
        )

    return OpenCVCameraSource(
        device=target,
        width=config.camera.width,
        height=config.camera.height,
        fps=config.camera.fps,
        fourcc=config.camera.fourcc,
        warmup_seconds=config.camera.warmup_seconds,
    )
