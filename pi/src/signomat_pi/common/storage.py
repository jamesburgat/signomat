from __future__ import annotations

import shutil
from pathlib import Path

from .config import SignomatConfig, repo_root


class StorageManager:
    def __init__(self, config: SignomatConfig):
        base_dir = Path(config.app.base_data_dir)
        if not base_dir.is_absolute():
            base_dir = repo_root() / base_dir
        self.base_dir = base_dir

    def initialize(self) -> None:
        for path in (
            self.db_dir,
            self.trips_dir,
            self.queue_dir,
            self.config_dir,
            self.models_dir,
            self.exports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def db_dir(self) -> Path:
        return self.base_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "signomat.db"

    @property
    def trips_dir(self) -> Path:
        return self.base_dir / "trips"

    @property
    def queue_dir(self) -> Path:
        return self.base_dir / "queue"

    @property
    def config_dir(self) -> Path:
        return self.base_dir / "config"

    @property
    def models_dir(self) -> Path:
        return self.base_dir / "models"

    @property
    def exports_dir(self) -> Path:
        return self.base_dir / "exports"

    def trip_dir(self, trip_id: str) -> Path:
        path = self.trips_dir / trip_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def trip_paths(self, trip_id: str) -> dict[str, Path]:
        root = self.trip_dir(trip_id)
        paths = {
            "root": root,
            "video": root / "video",
            "frames_clean": root / "frames_clean",
            "frames_annotated": root / "frames_annotated",
            "crops": root / "crops",
            "gps": root / "gps",
            "logs": root / "logs",
            "thumb_clean": root / "thumbnails" / "clean",
            "thumb_annotated": root / "thumbnails" / "annotated",
            "thumb_crops": root / "thumbnails" / "crops",
            "diagnostics": root / "logs" / "diagnostics",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        return paths

    def storage_status(self) -> dict[str, int]:
        usage = shutil.disk_usage(self.base_dir)
        return {
            "total_mb": int(usage.total / 1024 / 1024),
            "used_mb": int(usage.used / 1024 / 1024),
            "free_mb": int(usage.free / 1024 / 1024),
        }

    def relative_path(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return str(path.relative_to(self.base_dir))
        except ValueError:
            return str(path)

