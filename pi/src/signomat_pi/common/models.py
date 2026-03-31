from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np


@dataclass(slots=True)
class FramePacket:
    frame: np.ndarray
    timestamp: datetime
    frame_id: int


@dataclass(slots=True)
class GPSPoint:
    timestamp_utc: str
    lat: float | None
    lon: float | None
    speed: float | None
    heading: float | None
    altitude: float | None
    fix_quality: str
    source: str


@dataclass(slots=True)
class DetectionCandidate:
    bbox: tuple[int, int, int, int]
    detector_label: str
    shape_label: str
    color_label: str
    confidence: float


@dataclass(slots=True)
class ClassificationResult:
    raw_label: str
    confidence: float


@dataclass(slots=True)
class TaxonomyResult:
    category_id: str
    category_label: str
    specific_label: str
    grouping_mode: str


@dataclass(slots=True)
class SavedAssets:
    clean_frame_path: str | None
    annotated_frame_path: str | None
    crop_path: str | None
    clean_thumbnail_path: str | None
    annotated_thumbnail_path: str | None
    crop_thumbnail_path: str | None


@dataclass(slots=True)
class ActiveSegment:
    video_segment_id: str
    start_timestamp_utc: str
    file_path: str
    start_dt: datetime
    frames_written: int = 0


@dataclass(slots=True)
class RecentDetection:
    event_id: str
    group_id: str
    category_id: str
    bbox: tuple[int, int, int, int]
    seen_at: datetime

