from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import cv2

from signomat_pi.common.config import resolve_repo_path
from signomat_pi.common.models import ClassificationResult, DetectionCandidate
from signomat_pi.common.utils import utc_now_text
from signomat_pi.inference_service.pipeline import (
    DetectorLabelClassifier,
    FramePreprocessor,
    MockSignClassifier,
    UltralyticsCropClassifier,
    uses_classifier_confidence_gate,
)
from signomat_pi.inference_service.taxonomy import TaxonomyMapper


class ReplayEvaluator:
    def __init__(self, config, storage, database, classifier=None):
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
        self.classifier = classifier

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

            classified = self._classifier().classify(processed, candidate)
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

    def classify_trip(
        self,
        trip_id: str,
        *,
        export: bool = True,
        persist: bool = True,
        progress_callback=None,
        should_pause=None,
        stop_event: threading.Event | None = None,
    ) -> dict:
        detections = self.database.detections_for_trip(trip_id)
        if not detections:
            return {"ok": False, "trip_id": trip_id, "message": "trip has no detections to classify"}

        grouped = _group_trip_detections(detections)
        result = {
            "ok": True,
            "trip_id": trip_id,
            "mode": "post_trip_strong_frame_classification",
            "evaluated_at_utc": utc_now_text(),
            "total_detections": len(detections),
            "total_groups": len(grouped),
            "processed_groups": 0,
            "updated_detections": 0,
            "missing_frames": 0,
            "invalid_rows": 0,
            "classified_groups": 0,
            "unknown_groups": 0,
            "groups": [],
        }

        for group_index, (group_id, rows) in enumerate(grouped.items(), start=1):
            if stop_event is not None and stop_event.is_set():
                return {
                    **result,
                    "ok": False,
                    "message": "classification job stopped",
                    "stopped": True,
                }
            while should_pause is not None and should_pause():
                if stop_event is not None and stop_event.is_set():
                    return {
                        **result,
                        "ok": False,
                        "message": "classification job stopped",
                        "stopped": True,
                    }
                if progress_callback is not None:
                    progress_callback(
                        {
                            "state": "waiting_for_idle",
                            "trip_id": trip_id,
                            "group_id": group_id,
                            "processed_groups": result["processed_groups"],
                            "total_groups": result["total_groups"],
                        }
                    )
                time.sleep(0.25)

            if progress_callback is not None:
                progress_callback(
                    {
                        "state": "running",
                        "trip_id": trip_id,
                        "group_id": group_id,
                        "processed_groups": result["processed_groups"],
                        "total_groups": result["total_groups"],
                    }
                )

            best = self._best_group_classification(rows)
            if best is None:
                result["missing_frames"] += 1
                result["processed_groups"] += 1
                continue

            representative_row, classified = best
            if (
                classified.raw_label != "unknown_sign"
                and uses_classifier_confidence_gate(self._classifier())
                and classified.confidence < self.config.inference.min_classifier_confidence
            ):
                classified = ClassificationResult("unknown_sign", classified.confidence)
            taxonomy = self.taxonomy.map_label(classified.raw_label)
            review_state = "machine_classified" if classified.raw_label != "unknown_sign" else "classification_unknown"
            event_ids = [row["event_id"] for row in rows]

            if persist:
                self.database.update_detections_classification(
                    event_ids,
                    raw_classifier_label=classified.raw_label,
                    classifier_confidence=classified.confidence,
                    category_id=taxonomy.category_id,
                    category_label=taxonomy.category_label,
                    specific_label=taxonomy.specific_label,
                    grouping_mode=taxonomy.grouping_mode,
                    review_state=review_state,
                )
                for row in rows:
                    self.database.enqueue_upload(
                        "detection_metadata",
                        None,
                        "detections",
                        row["event_id"],
                        {"trip_id": trip_id, "event_id": row["event_id"], "source": "post_trip_classification"},
                    )

            result["processed_groups"] += 1
            result["updated_detections"] += len(rows)
            if classified.raw_label == "unknown_sign":
                result["unknown_groups"] += 1
            else:
                result["classified_groups"] += 1
            if len(result["groups"]) < 25:
                result["groups"].append(
                    {
                        "group_id": group_id,
                        "event_count": len(rows),
                        "representative_event_id": representative_row["event_id"],
                        "raw_classifier_label": classified.raw_label,
                        "classifier_confidence": classified.confidence,
                        "category_label": taxonomy.category_label,
                        "specific_label": taxonomy.specific_label,
                        "review_state": review_state,
                    }
                )

        if export:
            export_path = self.storage.exports_dir / f"classify_{trip_id}_{utc_now_text().replace(':', '-')}.json"
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

    def _classifier(self):
        if self.classifier is None:
            self.classifier = _build_replay_classifier(self.config)
        return self.classifier

    def _best_group_classification(self, rows: list[dict]) -> tuple[dict, ClassificationResult] | None:
        ranked_rows = sorted(rows, key=_classification_priority, reverse=True)[:3]
        best: tuple[dict, ClassificationResult] | None = None
        for row in ranked_rows:
            classified = self._classify_row(row)
            if classified is None:
                continue
            if best is None or classified.confidence > best[1].confidence:
                best = (row, classified)
        return best

    def _classify_row(self, row: dict) -> ClassificationResult | None:
        bbox = _bbox_from_row(row)
        if bbox is None:
            return None

        frame_path = self._absolute_media_path(row.get("clean_frame_path"))
        if frame_path is None or not frame_path.exists():
            return None

        frame = cv2.imread(str(frame_path))
        if frame is None:
            return None

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
        return self._classifier().classify(processed, candidate)


class PostTripClassificationManager:
    def __init__(self, evaluator: ReplayEvaluator, database, can_run_callback):
        self.evaluator = evaluator
        self.database = database
        self.can_run_callback = can_run_callback
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._status = {
            "state": "idle",
            "running": False,
            "current_trip_id": None,
            "current_stage": None,
            "processed_groups": 0,
            "total_groups": 0,
            "progress_pct": 0,
            "queued_trip_ids": [],
            "last_completed_trip_id": None,
            "last_completed_at": None,
            "last_error": None,
            "last_result": None,
        }

    def status(self) -> dict:
        with self._lock:
            snapshot = dict(self._status)
            snapshot["queued_trip_ids"] = list(self._queue)
        pending_trips = self.database.pending_post_classification_trips(limit=5)
        snapshot["pending_trips"] = pending_trips
        snapshot["pending_trip_count"] = len(pending_trips)
        snapshot["launchable"] = (not snapshot["running"]) and bool(pending_trips)
        return snapshot

    def enqueue_trip(self, trip_id: str) -> dict:
        with self._lock:
            if trip_id not in self._queue and trip_id != self._status["current_trip_id"]:
                self._queue.append(trip_id)
                self._status["queued_trip_ids"] = list(self._queue)
            self._status["state"] = "queued" if self._queue else self._status["state"]
        self._ensure_thread()
        return self.status()

    def launch(self, trip_id: str | None = None) -> dict:
        target_trip_id = trip_id
        if target_trip_id is None:
            pending = self.database.pending_post_classification_trips(limit=1)
            if not pending:
                return {"ok": False, "message": "no pending trips available for post-trip classification", "status": self.status()}
            target_trip_id = pending[0]["trip_id"]
        status = self.enqueue_trip(target_trip_id)
        return {"ok": True, "trip_id": target_trip_id, "status": status}

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._worker, name="post-trip-classifier", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            with self._lock:
                if not self._queue:
                    self._status["state"] = "idle"
                    self._status["running"] = False
                    self._status["current_trip_id"] = None
                    self._status["current_stage"] = None
                    self._status["queued_trip_ids"] = []
                    return
                trip_id = self._queue.pop(0)
                self._status["queued_trip_ids"] = list(self._queue)
                self._status["current_trip_id"] = trip_id
                self._status["state"] = "queued"
                self._status["running"] = True

            while not self.stop_event.is_set() and not self.can_run_callback():
                with self._lock:
                    self._status["state"] = "waiting_for_idle"
                    self._status["current_stage"] = "waiting for trip to end"
                time.sleep(0.25)
            if self.stop_event.is_set():
                return

            with self._lock:
                self._status["state"] = "running"
                self._status["current_stage"] = "classifying strong frames"
                self._status["processed_groups"] = 0
                self._status["total_groups"] = 0
                self._status["progress_pct"] = 0
                self._status["last_error"] = None

            def _progress(update: dict) -> None:
                total_groups = int(update.get("total_groups") or 0)
                processed_groups = int(update.get("processed_groups") or 0)
                progress_pct = int(round((processed_groups / total_groups) * 100)) if total_groups else 0
                with self._lock:
                    self._status["state"] = update.get("state") or "running"
                    self._status["current_trip_id"] = trip_id
                    self._status["current_stage"] = "classifying strong frames"
                    self._status["processed_groups"] = processed_groups
                    self._status["total_groups"] = total_groups
                    self._status["progress_pct"] = progress_pct

            result = self.evaluator.classify_trip(
                trip_id,
                export=True,
                persist=True,
                progress_callback=_progress,
                should_pause=lambda: not self.can_run_callback(),
                stop_event=self.stop_event,
            )

            with self._lock:
                self._status["running"] = False
                self._status["last_result"] = result
                if result.get("ok"):
                    self._status["state"] = "completed"
                    self._status["last_completed_trip_id"] = trip_id
                    self._status["last_completed_at"] = utc_now_text()
                    self._status["last_error"] = None
                    self._status["current_stage"] = "classification complete"
                    self._status["processed_groups"] = int(result.get("processed_groups") or 0)
                    self._status["total_groups"] = int(result.get("total_groups") or 0)
                    self._status["progress_pct"] = 100 if self._status["total_groups"] else 0
                else:
                    self._status["state"] = "error" if not result.get("stopped") else "idle"
                    self._status["last_error"] = result.get("message")
                    self._status["current_stage"] = result.get("message")
                    self._status["processed_groups"] = int(result.get("processed_groups") or 0)
                    self._status["total_groups"] = int(result.get("total_groups") or 0)
                    self._status["progress_pct"] = int(
                        round((self._status["processed_groups"] / self._status["total_groups"]) * 100)
                    ) if self._status["total_groups"] else 0


def _build_replay_classifier(config):
    backend = config.inference.classifier_backend.lower()
    if backend == "yolo":
        return UltralyticsCropClassifier(
            model_path=resolve_repo_path(config.inference.classifier_model_path),
            imgsz=config.inference.classifier_imgsz,
            verbose=config.inference.model_verbose,
        )
    if backend in {"none", "disabled", "detector_label"}:
        model_path = resolve_repo_path(config.inference.classifier_model_path)
        # Keep live inference lightweight, but use the offline classifier model
        # for post-trip replay when it is available locally.
        if model_path.exists():
            return UltralyticsCropClassifier(
                model_path=model_path,
                imgsz=config.inference.classifier_imgsz,
                verbose=config.inference.model_verbose,
            )
        return DetectorLabelClassifier()
    if backend == "mock_classifier":
        return MockSignClassifier()
    raise ValueError(f"unsupported classifier backend: {config.inference.classifier_backend}")


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


def _group_trip_detections(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = row.get("dedupe_group_id") or row["event_id"]
        grouped.setdefault(key, []).append(row)
    return grouped


def _classification_priority(row: dict) -> tuple[float, int, str]:
    left = int(row.get("bbox_left") or 0)
    top = int(row.get("bbox_top") or 0)
    right = int(row.get("bbox_right") or 0)
    bottom = int(row.get("bbox_bottom") or 0)
    area = max(0, right - left) * max(0, bottom - top)
    detector_confidence = float(row.get("detector_confidence") or 0.0)
    return detector_confidence, area, str(row.get("timestamp_utc") or "")
