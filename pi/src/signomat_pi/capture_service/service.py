from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

from signomat_pi.common.config import SignomatConfig
from signomat_pi.common.models import ActiveSegment, FramePacket
from signomat_pi.common.storage import StorageManager
from signomat_pi.common.utils import stable_id, utc_now, utc_now_text
from signomat_pi.capture_service.camera_sources import create_camera_source


LOGGER = logging.getLogger(__name__)


class CaptureService:
    def __init__(self, config: SignomatConfig, storage: StorageManager, database):
        self.config = config
        self.storage = storage
        self.database = database
        self.camera = create_camera_source(config)
        self.running = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.frame_id = 0
        self.latest_packet: FramePacket | None = None
        self.active_trip_id: str | None = None
        self.recording_enabled = False
        self.writer = None
        self.active_segment: ActiveSegment | None = None

    def start(self) -> None:
        self.camera.start()
        self.running.set()
        self.thread = threading.Thread(target=self._loop, name="capture-service", daemon=True)
        self.thread.start()
        LOGGER.info("capture service started: %s", self.camera.describe())

    def stop(self) -> None:
        self.running.clear()
        if self.thread:
            self.thread.join(timeout=3)
        self._close_segment()
        self.camera.stop()

    def set_trip(self, trip_id: str | None) -> None:
        with self.lock:
            self.active_trip_id = trip_id
            if trip_id is None:
                self.recording_enabled = False
                self._close_segment()

    def start_recording(self) -> None:
        with self.lock:
            self.recording_enabled = True

    def stop_recording(self) -> None:
        with self.lock:
            self.recording_enabled = False
            self._close_segment()

    def latest_frame(self) -> FramePacket | None:
        with self.lock:
            if self.latest_packet is None:
                return None
            return FramePacket(self.latest_packet.frame.copy(), self.latest_packet.timestamp, self.latest_packet.frame_id)

    def current_segment_reference(self, timestamp: datetime) -> tuple[str | None, int | None]:
        with self.lock:
            if not self.active_segment:
                return None, None
            delta_ms = int((timestamp - self.active_segment.start_dt).total_seconds() * 1000)
            return self.active_segment.video_segment_id, max(delta_ms, 0)

    def _loop(self) -> None:
        while self.running.is_set():
            frame = self.camera.capture_frame()
            timestamp = utc_now()
            frame = self._apply_rotation(frame)
            with self.lock:
                self.frame_id += 1
                self.latest_packet = FramePacket(frame.copy(), timestamp, self.frame_id)
                if self.recording_enabled and self.active_trip_id:
                    self._write_frame(frame, timestamp)

    def _apply_rotation(self, frame):
        rotation = self.config.camera.rotation % 360
        if rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def _low_storage(self) -> bool:
        return self.storage.storage_status()["free_mb"] < self.config.camera.low_storage_stop_mb

    def _open_segment(self, frame_shape) -> None:
        if not self.active_trip_id:
            return
        if self._low_storage():
            self.recording_enabled = False
            self.database.add_device_event("storage.low", "warning", "recording stopped because free space is low")
            return
        trip_paths = self.storage.trip_paths(self.active_trip_id)
        segment_id = stable_id("segment")
        timestamp_utc = utc_now_text()
        file_path = trip_paths["video"] / f"{segment_id}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*self.config.camera.codec[:4])
        height, width = frame_shape[:2]
        self.writer = cv2.VideoWriter(str(file_path), fourcc, self.config.camera.fps, (width, height))
        self.active_segment = ActiveSegment(
            video_segment_id=segment_id,
            start_timestamp_utc=timestamp_utc,
            file_path=str(file_path),
            start_dt=utc_now(),
        )
        self.database.create_video_segment(
            {
                "video_segment_id": segment_id,
                "trip_id": self.active_trip_id,
                "start_timestamp_utc": timestamp_utc,
                "file_path": self.storage.relative_path(file_path),
            }
        )

    def _close_segment(self) -> None:
        if self.writer is None or self.active_segment is None:
            self.writer = None
            self.active_segment = None
            return
        self.writer.release()
        file_path = Path(self.active_segment.file_path)
        duration_sec = self.active_segment.frames_written / max(self.config.camera.fps, 1)
        self.database.finalize_video_segment(
            self.active_segment.video_segment_id,
            utc_now_text(),
            file_path.stat().st_size if file_path.exists() else 0,
            duration_sec,
        )
        self.database.enqueue_upload(
            "video_segment",
            self.storage.relative_path(file_path),
            "video_segments",
            self.active_segment.video_segment_id,
            {"trip_id": self.active_trip_id, "type": "video_segment"},
        )
        self.writer = None
        self.active_segment = None

    def _write_frame(self, frame, timestamp: datetime) -> None:
        if self.writer is None or self.active_segment is None:
            self._open_segment(frame.shape)
        if self.writer is None or self.active_segment is None:
            return
        elapsed = (timestamp - self.active_segment.start_dt).total_seconds()
        if elapsed >= self.config.camera.chunk_seconds:
            self._close_segment()
            self._open_segment(frame.shape)
            if self.writer is None or self.active_segment is None:
                return
        self.writer.write(frame)
        self.active_segment.frames_written += 1

