from __future__ import annotations

import json
from pathlib import Path

import cv2

from signomat_pi.common.models import DetectionCandidate
from signomat_pi.common.utils import utc_now_text
from signomat_pi.inference_service.pipeline import FramePreprocessor, HeuristicSignClassifier
from signomat_pi.inference_service.taxonomy import TaxonomyMapper


class ReplayEvaluator:
    def __init__(self, config, storage, database):
        self.config = config
        self.storage = storage
        self.database = database
        taxonomy_path = Path(config.taxonomy.config_path)
        if not taxonomy_path.is_absolute():
            taxonomy_path = Path.cwd() / taxonomy_path
        if not taxonomy_path.exists():
            taxonomy_path = Path(__file__).resolve().parents[4] / config.taxonomy.config_path
        self.taxonomy = TaxonomyMapper(taxonomy_path)
        self.preprocessor = FramePreprocessor(config.inference.preprocessing)
        self.classifier = HeuristicSignClassifier()

    def evaluate_trip(self, trip_id: str, *, export: bool = True) -> dict:
        detections = self.database.detections_for_trip(trip_id)
        if not detections:
            return {"ok": False, "trip_id": trip_id, "message": "trip has no detections to replay"}

        result = {
            "ok": True,
            "trip_id": trip_id,
            "mode": "stored_detection_frame_replay",
            "evaluated_at_utc": utc_now_text(),
            "total_detections": len(detections),
            "evaluated_detections": 0,
            "missing_frames": 0,
            "invalid_rows": 0,
            "raw_classifier_matches": 0,
            "taxonomy_matches": 0,
            "stored_category_counts": {},
            "replayed_category_counts": {},
            "confusion_pairs": {},
            "disagreements": [],
        }

        for row in detections:
            stored_category = row["category_label"] or "unknown_sign"
            result["stored_category_counts"][stored_category] = result["stored_category_counts"].get(stored_category, 0) + 1

            bbox = _bbox_from_row(row)
            if bbox is None:
                result["invalid_rows"] += 1
                continue

            frame_path = self._absolute_media_path(row.get("clean_frame_path"))
            if frame_path is None or not frame_path.exists():
                result["missing_frames"] += 1
                continue

            frame = cv2.imread(str(frame_path))
            if frame is None:
                result["missing_frames"] += 1
                continue

            processed = self.preprocessor.apply(frame)
            x1, y1, x2, y2 = bbox
            x1 = max(0, min(x1, processed.shape[1] - 1))
            x2 = max(x1 + 1, min(x2, processed.shape[1]))
            y1 = max(0, min(y1, processed.shape[0] - 1))
            y2 = max(y1 + 1, min(y2, processed.shape[0]))

            color_label, shape_label = _parse_detector_label(row.get("raw_detector_label"))
            candidate = DetectionCandidate(
                bbox=(x1, y1, x2, y2),
                detector_label=row.get("raw_detector_label") or f"{color_label}_{shape_label}",
                shape_label=shape_label,
                color_label=color_label,
                confidence=row.get("detector_confidence") or 0.0,
            )

            classified = self.classifier.classify(processed, candidate)
            taxonomy = self.taxonomy.map_label(classified.raw_label)

            result["evaluated_detections"] += 1
            replayed_category = taxonomy.category_label
            result["replayed_category_counts"][replayed_category] = result["replayed_category_counts"].get(replayed_category, 0) + 1
            confusion_key = f"{stored_category}->{replayed_category}"
            result["confusion_pairs"][confusion_key] = result["confusion_pairs"].get(confusion_key, 0) + 1

            if classified.raw_label == row.get("raw_classifier_label"):
                result["raw_classifier_matches"] += 1
            stored_specific = row.get("specific_label")
            replay_specific = taxonomy.specific_label
            if replayed_category == stored_category and replay_specific == stored_specific:
                result["taxonomy_matches"] += 1
            else:
                if len(result["disagreements"]) < 25:
                    result["disagreements"].append(
                        {
                            "event_id": row["event_id"],
                            "stored_raw_classifier_label": row.get("raw_classifier_label"),
                            "replayed_raw_classifier_label": classified.raw_label,
                            "stored_category_label": stored_category,
                            "replayed_category_label": replayed_category,
                            "stored_specific_label": row.get("specific_label"),
                            "replayed_specific_label": taxonomy.specific_label,
                            "clean_frame_path": row.get("clean_frame_path"),
                        }
                    )

        evaluated = max(result["evaluated_detections"], 1)
        result["raw_classifier_match_rate"] = round(result["raw_classifier_matches"] / evaluated, 4) if result["evaluated_detections"] else 0.0
        result["taxonomy_match_rate"] = round(result["taxonomy_matches"] / evaluated, 4) if result["evaluated_detections"] else 0.0

        if export:
            export_path = self.storage.exports_dir / f"replay_{trip_id}_{utc_now_text().replace(':', '-')}.json"
            export_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            result["export_path"] = self.storage.relative_path(export_path)

        return result

    def _absolute_media_path(self, relative_path: str | None) -> Path | None:
        if not relative_path:
            return None
        path = Path(relative_path)
        if path.is_absolute():
            return path
        return self.storage.base_dir / path


def _bbox_from_row(row: dict) -> tuple[int, int, int, int] | None:
    values = [row.get("bbox_left"), row.get("bbox_top"), row.get("bbox_right"), row.get("bbox_bottom")]
    if any(value is None for value in values):
        return None
    return int(values[0]), int(values[1]), int(values[2]), int(values[3])


def _parse_detector_label(raw: str | None) -> tuple[str, str]:
    if raw and "_" in raw:
        color, shape = raw.split("_", 1)
        return color, shape
    return "unknown", "unknown"
