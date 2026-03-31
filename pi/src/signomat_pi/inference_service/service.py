from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from signomat_pi.common.storage import StorageManager
from signomat_pi.common.utils import utc_now_text
from signomat_pi.inference_service.pipeline import AssetWriter, ColorShapeCandidateDetector, Deduplicator, FramePreprocessor, HeuristicSignClassifier
from signomat_pi.inference_service.taxonomy import TaxonomyMapper


LOGGER = logging.getLogger(__name__)


class InferenceService:
    def __init__(self, config, storage: StorageManager, database, capture_service, gps_service, runtime_callbacks):
        self.config = config
        self.storage = storage
        self.database = database
        self.capture_service = capture_service
        self.gps_service = gps_service
        self.runtime_callbacks = runtime_callbacks
        taxonomy_path = Path(config.taxonomy.config_path)
        if not taxonomy_path.is_absolute():
            taxonomy_path = Path.cwd() / taxonomy_path
        if not taxonomy_path.exists():
            taxonomy_path = Path(__file__).resolve().parents[4] / config.taxonomy.config_path
        self.taxonomy = TaxonomyMapper(taxonomy_path)
        self.preprocessor = FramePreprocessor(config.inference.preprocessing)
        self.detector = ColorShapeCandidateDetector(config.inference)
        self.classifier = HeuristicSignClassifier()
        self.deduper = Deduplicator(config.inference.dedupe_window_seconds, config.inference.dedupe_iou_threshold)
        self.assets = AssetWriter(storage, config.inference.thumbnail_max_edge)
        self.running = threading.Event()
        self.enabled = config.inference.enabled
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.running.set()
        self.thread = threading.Thread(target=self._loop, name="inference-service", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running.clear()
        if self.thread:
            self.thread.join(timeout=3)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def _loop(self) -> None:
        while self.running.is_set():
            try:
                if not self.enabled:
                    time.sleep(self.config.inference.interval_seconds)
                    continue
                trip_id = self.runtime_callbacks.current_trip_id()
                if not trip_id:
                    time.sleep(self.config.inference.interval_seconds)
                    continue
                packet = self.capture_service.latest_frame()
                if packet is None:
                    time.sleep(self.config.inference.interval_seconds)
                    continue
                processed = self.preprocessor.apply(packet.frame)
                for candidate in self.detector.detect(processed):
                    if candidate.confidence < self.config.inference.min_detector_confidence:
                        continue
                    classified = self.classifier.classify(processed, candidate)
                    if classified.confidence < self.config.inference.min_classifier_confidence:
                        continue
                    if classified.raw_label == "unknown_sign" and not self.config.inference.save_unknown_signs:
                        continue
                    taxonomy = self.taxonomy.map_label(classified.raw_label)
                    accept, dedupe_ref = self.deduper.accept_or_suppress(taxonomy.category_id, candidate.bbox, packet.timestamp)
                    if not accept:
                        self.database.increment_suppressed_count(dedupe_ref)
                        continue
                    event_id = dedupe_ref
                    group_id = self.deduper.group_id_for_event(event_id)
                    assets = self.assets.save_detection_assets(
                        trip_id=trip_id,
                        event_id=event_id,
                        frame=processed,
                        bbox=candidate.bbox,
                        label=taxonomy.category_label,
                        confidence=classified.confidence,
                        save_crop=self.config.inference.save_crops,
                    )
                    gps = self.gps_service.latest_sample()
                    segment_id, offset_ms = self.capture_service.current_segment_reference(packet.timestamp)
                    payload = {
                        "event_id": event_id,
                        "trip_id": trip_id,
                        "timestamp_utc": utc_now_text(),
                        "gps_lat": gps.lat if gps else None,
                        "gps_lon": gps.lon if gps else None,
                        "gps_speed": gps.speed if gps else None,
                        "heading": gps.heading if gps else None,
                        "category_id": taxonomy.category_id,
                        "category_label": taxonomy.category_label,
                        "specific_label": taxonomy.specific_label,
                        "grouping_mode": taxonomy.grouping_mode,
                        "raw_detector_label": candidate.detector_label,
                        "raw_classifier_label": classified.raw_label,
                        "detector_confidence": candidate.confidence,
                        "classifier_confidence": classified.confidence,
                        "bbox_left": candidate.bbox[0],
                        "bbox_top": candidate.bbox[1],
                        "bbox_right": candidate.bbox[2],
                        "bbox_bottom": candidate.bbox[3],
                        "annotated_frame_path": assets.annotated_frame_path,
                        "clean_frame_path": assets.clean_frame_path,
                        "sign_crop_path": assets.crop_path,
                        "annotated_thumbnail_path": assets.annotated_thumbnail_path,
                        "clean_thumbnail_path": assets.clean_thumbnail_path,
                        "sign_crop_thumbnail_path": assets.crop_thumbnail_path,
                        "video_segment_id": segment_id,
                        "video_timestamp_offset_ms": offset_ms,
                        "dedupe_group_id": group_id,
                        "suppressed_nearby_count": 0,
                        "upload_state": "pending",
                        "review_state": "unreviewed",
                        "notes": None,
                    }
                    self.database.add_detection(payload)
                    for local_path in (assets.clean_frame_path, assets.annotated_frame_path, assets.crop_path):
                        if local_path:
                            self.database.enqueue_upload(
                                "media_asset",
                                local_path,
                                "detections",
                                event_id,
                                {"trip_id": trip_id, "event_id": event_id},
                            )
                    self.database.enqueue_upload("detection_metadata", None, "detections", event_id, {"trip_id": trip_id})
                    self.runtime_callbacks.on_detection(payload)
                time.sleep(self.config.inference.interval_seconds)
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("inference loop failed: %s", exc)
                self.database.add_device_event("inference.error", "error", str(exc))
                time.sleep(self.config.inference.interval_seconds)
