from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from signomat_pi.common.models import ClassificationResult, DetectionCandidate, RecentDetection, SavedAssets, TaxonomyResult
from signomat_pi.common.storage import StorageManager
from signomat_pi.common.utils import clamp, ensure_parent, iou_xyxy, stable_id, utc_now_text


LOGGER = logging.getLogger(__name__)


class FramePreprocessor:
    def __init__(self, config):
        self.config = config

    def apply(self, frame: np.ndarray) -> np.ndarray:
        output = frame
        if self.config.downscale_width and frame.shape[1] > self.config.downscale_width:
            ratio = self.config.downscale_width / frame.shape[1]
            output = cv2.resize(frame, (self.config.downscale_width, int(frame.shape[0] * ratio)))
        if self.config.contrast_normalization:
            lab = cv2.cvtColor(output, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            output = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        return output


class ColorShapeCandidateDetector:
    def __init__(self, config):
        self.config = config

    def detect(self, frame: np.ndarray) -> list[DetectionCandidate]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        masks = {
            "red": cv2.bitwise_or(
                cv2.inRange(hsv, (0, 70, 50), (10, 255, 255)),
                cv2.inRange(hsv, (170, 70, 50), (180, 255, 255)),
            ),
            "yellow": cv2.inRange(hsv, (15, 70, 70), (40, 255, 255)),
            "blue": cv2.inRange(hsv, (95, 70, 60), (130, 255, 255)),
        }
        candidates: list[DetectionCandidate] = []
        frame_area = max(frame.shape[0] * frame.shape[1], 1)
        kernel = np.ones((5, 5), dtype=np.uint8)
        for color_label, mask in masks.items():
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self.config.min_box_area:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if not self._passes_bbox_filters(frame.shape, x, y, w, h, area, frame_area):
                    continue
                bbox = (x, y, x + w, y + h)
                shape = self._shape_from_contour(contour)
                if shape == "unknown":
                    continue
                fill_ratio = area / max(w * h, 1)
                conf = clamp(
                    0.40
                    + (area / frame_area) * 14
                    + min(fill_ratio, 0.75) * 0.45
                    + self._shape_bonus(shape),
                    0.40,
                    0.99,
                )
                candidates.append(
                    DetectionCandidate(
                        bbox=bbox,
                        detector_label=f"{color_label}_{shape}",
                        shape_label=shape,
                        color_label=color_label,
                        confidence=conf,
                    )
                )
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[: self.config.max_candidates]

    def _passes_bbox_filters(self, frame_shape, x: int, y: int, w: int, h: int, area: float, frame_area: int) -> bool:
        if min(w, h) < 24:
            return False
        margin = self.config.border_ignore_margin_px
        frame_h, frame_w = frame_shape[:2]
        if x <= margin or y <= margin or (x + w) >= (frame_w - margin) or (y + h) >= (frame_h - margin):
            return False
        aspect = max(w, h) / max(min(w, h), 1)
        if aspect > 1.35:
            return False
        if (area / frame_area) > self.config.max_box_area_ratio:
            return False
        fill_ratio = area / max(w * h, 1)
        if fill_ratio < self.config.min_box_fill_ratio:
            return False
        return True

    def _shape_bonus(self, shape: str) -> float:
        bonuses = {
            "octagon": 0.16,
            "triangle": 0.14,
            "diamond": 0.12,
            "circle": 0.10,
        }
        return bonuses.get(shape, 0.0)

    def _shape_from_contour(self, contour) -> str:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        vertices = len(approx)
        area = cv2.contourArea(contour)
        if perimeter <= 0:
            return "unknown"
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        if 7 <= vertices <= 10:
            return "octagon"
        if vertices == 3:
            return "triangle"
        if vertices == 4:
            rect = cv2.minAreaRect(contour)
            _, (w, h), angle = rect
            if min(w, h) > 0:
                aspect = max(w, h) / min(w, h)
                if aspect < 1.25 and 20 <= abs(angle) <= 70:
                    return "diamond"
            return "quad"
        if circularity > 0.65:
            return "circle"
        return "unknown"


class HeuristicSignClassifier:
    def __init__(self) -> None:
        self.speed_templates = self._build_speed_templates(("25", "35", "45", "55"))

    def classify(self, frame: np.ndarray, candidate: DetectionCandidate) -> ClassificationResult:
        x1, y1, x2, y2 = candidate.bbox
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return ClassificationResult("unknown_sign", 0.1)
        if self._crop_is_too_dark(crop):
            return ClassificationResult("unknown_sign", 0.1)
        if candidate.color_label == "red" and candidate.shape_label == "octagon":
            return ClassificationResult("stop", 0.94)
        if candidate.color_label == "red" and candidate.shape_label == "triangle":
            return ClassificationResult("yield", 0.90)
        if candidate.color_label == "yellow" and candidate.shape_label == "diamond":
            if self._has_cross_pattern(crop):
                return ClassificationResult("crossing", 0.76)
            return ClassificationResult("warning_diamond", 0.72)
        if candidate.color_label == "blue" and candidate.shape_label == "circle":
            return ClassificationResult("mandatory_round", 0.78)
        if candidate.color_label == "red" and candidate.shape_label == "circle":
            speed = self._match_speed_limit(crop)
            if speed:
                return ClassificationResult(f"speed_limit_{speed}", 0.82)
            return ClassificationResult("prohibition_round", 0.70)
        return ClassificationResult("unknown_sign", 0.20)

    def _crop_is_too_dark(self, crop: np.ndarray) -> bool:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return float(np.mean(gray)) < 25.0

    def _build_speed_templates(self, values: tuple[str, ...]) -> dict[str, np.ndarray]:
        templates = {}
        for value in values:
            canvas = np.full((96, 96), 255, dtype=np.uint8)
            cv2.putText(canvas, value, (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.25, 0, 3)
            _, canvas = cv2.threshold(canvas, 180, 255, cv2.THRESH_BINARY_INV)
            templates[value] = canvas
        return templates

    def _match_speed_limit(self, crop: np.ndarray) -> str | None:
        h, w = crop.shape[:2]
        inner = crop[int(h * 0.2): int(h * 0.8), int(w * 0.2): int(w * 0.8)]
        if inner.size == 0:
            return None
        gray = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
        resized = cv2.resize(thresh, (96, 96))
        best_score = None
        best_value = None
        for value, template in self.speed_templates.items():
            score = float(np.mean(np.abs(resized.astype(np.float32) - template.astype(np.float32))))
            if best_score is None or score < best_score:
                best_score = score
                best_value = value
        if best_score is not None and best_score < 95:
            return best_value
        return None

    def _has_cross_pattern(self, crop: np.ndarray) -> bool:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        diag1 = np.mean(np.diag(edges))
        diag2 = np.mean(np.diag(np.fliplr(edges)))
        return diag1 > 10 and diag2 > 10


class Deduplicator:
    def __init__(self, window_seconds: float, iou_threshold: float):
        self.window = timedelta(seconds=window_seconds)
        self.iou_threshold = iou_threshold
        self.recent: deque[RecentDetection] = deque(maxlen=64)

    def accept_or_suppress(self, category_id: str, bbox: tuple[int, int, int, int], seen_at: datetime) -> tuple[bool, str]:
        self._trim(seen_at)
        for item in self.recent:
            if item.category_id != category_id:
                continue
            if iou_xyxy(item.bbox, bbox) >= self.iou_threshold:
                item.seen_at = seen_at
                return False, item.event_id
        group_id = stable_id("dedupe")
        event_id = stable_id("event")
        self.recent.append(RecentDetection(event_id=event_id, group_id=group_id, category_id=category_id, bbox=bbox, seen_at=seen_at))
        return True, event_id

    def group_id_for_event(self, event_id: str) -> str | None:
        for item in self.recent:
            if item.event_id == event_id:
                return item.group_id
        return None

    def _trim(self, now: datetime) -> None:
        while self.recent and now - self.recent[0].seen_at > self.window:
            self.recent.popleft()


class AssetWriter:
    def __init__(self, storage: StorageManager, thumbnail_max_edge: int):
        self.storage = storage
        self.thumbnail_max_edge = thumbnail_max_edge

    def save_detection_assets(
        self,
        trip_id: str,
        event_id: str,
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
        label: str,
        confidence: float,
        save_crop: bool,
    ) -> SavedAssets:
        paths = self.storage.trip_paths(trip_id)
        clean = paths["frames_clean"] / f"{event_id}.jpg"
        annotated = paths["frames_annotated"] / f"{event_id}.jpg"
        crop_path = paths["crops"] / f"{event_id}.jpg" if save_crop else None
        clean_thumb = paths["thumb_clean"] / f"{event_id}.jpg"
        annotated_thumb = paths["thumb_annotated"] / f"{event_id}.jpg"
        crop_thumb = paths["thumb_crops"] / f"{event_id}.jpg" if save_crop else None

        cv2.imwrite(str(ensure_parent(clean)), frame)
        self._save_thumbnail(frame, clean_thumb)

        annotated_frame = frame.copy()
        x1, y1, x2, y2 = bbox
        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
        cv2.putText(
            annotated_frame,
            f"{label} {confidence:.2f}",
            (x1, max(28, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.imwrite(str(ensure_parent(annotated)), annotated_frame)
        self._save_thumbnail(annotated_frame, annotated_thumb)

        if save_crop and crop_path is not None:
            crop = frame[y1:y2, x1:x2]
            cv2.imwrite(str(ensure_parent(crop_path)), crop)
            self._save_thumbnail(crop, crop_thumb)

        return SavedAssets(
            clean_frame_path=self.storage.relative_path(clean),
            annotated_frame_path=self.storage.relative_path(annotated),
            crop_path=self.storage.relative_path(crop_path),
            clean_thumbnail_path=self.storage.relative_path(clean_thumb),
            annotated_thumbnail_path=self.storage.relative_path(annotated_thumb),
            crop_thumbnail_path=self.storage.relative_path(crop_thumb),
        )

    def _save_thumbnail(self, image: np.ndarray, target: Path | None) -> None:
        if target is None or image.size == 0:
            return
        h, w = image.shape[:2]
        scale = min(1.0, self.thumbnail_max_edge / max(h, w))
        thumb = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))))
        cv2.imwrite(str(ensure_parent(target)), thumb)
