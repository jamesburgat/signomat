from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import asdict

from signomat_pi.common.models import GPSPoint
from signomat_pi.common.storage import StorageManager
from signomat_pi.common.utils import ensure_parent
from signomat_pi.gps_service.providers import create_gps_provider


LOGGER = logging.getLogger(__name__)


class GPSService:
    def __init__(self, config, storage: StorageManager, database):
        self.config = config
        self.storage = storage
        self.database = database
        self.provider = create_gps_provider(config)
        self.running = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.recent_samples: deque[GPSPoint] = deque(maxlen=config.gps.ring_buffer_size)
        self.active_trip_id: str | None = None
        self.health = "idle"

    def start(self) -> None:
        self.running.set()
        self.thread = threading.Thread(target=self._loop, name="gps-service", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running.clear()
        if self.thread:
            self.thread.join(timeout=3)

    def set_trip(self, trip_id: str | None) -> None:
        with self.lock:
            self.active_trip_id = trip_id

    def latest_sample(self) -> GPSPoint | None:
        with self.lock:
            return self.recent_samples[-1] if self.recent_samples else None

    def recent(self, limit: int = 20) -> list[GPSPoint]:
        with self.lock:
            return list(self.recent_samples)[-limit:]

    def _loop(self) -> None:
        while self.running.is_set():
            try:
                point = self.provider.read()
                with self.lock:
                    self.recent_samples.append(point)
                    self.health = point.fix_quality
                    trip_id = self.active_trip_id
                if trip_id:
                    self.database.add_gps_point(trip_id, point)
                    self._append_trip_log(trip_id, point)
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("gps sampling failed: %s", exc)
                with self.lock:
                    self.health = "error"
            time.sleep(self.config.gps.sample_interval_seconds)

    def _append_trip_log(self, trip_id: str, point: GPSPoint) -> None:
        gps_log = self.storage.trip_paths(trip_id)["gps"] / "breadcrumb.jsonl"
        ensure_parent(gps_log)
        with gps_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(point), separators=(",", ":")) + "\n")
