import cv2
import numpy as np
import pytest

from signomat_pi.common.config import load_config
from signomat_pi.common.models import DetectionCandidate
from signomat_pi.inference_service import service as service_module
from signomat_pi.inference_service.pipeline import (
    DetectorLabelClassifier,
    MockColorShapeDetector,
    MockSignClassifier,
    UltralyticsSignDetector,
)


def test_default_config_uses_learned_models_and_mock_config_keeps_mock_backends():
    default_config = load_config("pi/config/default.yaml")
    assert default_config.inference.detector_backend == "yolo"
    assert default_config.inference.classifier_backend == "yolo"
    assert default_config.inference.detector_model_path.endswith("_ncnn_model")
    assert default_config.inference.classifier_model_path.endswith("_ncnn_model")
    assert default_config.inference.save_crops is False
    assert default_config.inference.save_unknown_signs is True

    mock_config = load_config("pi/config/mock.yaml")
    assert mock_config.inference.detector_backend == "mock_detector"
    assert mock_config.inference.classifier_backend == "mock_classifier"
    assert mock_config.inference.save_crops is False


def test_learned_backend_init_errors_do_not_fall_back_to_mock_backends(monkeypatch):
    config = load_config("pi/config/default.yaml")
    service = service_module.InferenceService.__new__(service_module.InferenceService)
    service.config = config

    def raise_detector_error(**_kwargs):
        raise RuntimeError("detector load failed")

    def raise_classifier_error(**_kwargs):
        raise RuntimeError("classifier load failed")

    monkeypatch.setattr(service_module, "UltralyticsSignDetector", raise_detector_error)
    monkeypatch.setattr(service_module, "UltralyticsCropClassifier", raise_classifier_error)

    with pytest.raises(RuntimeError, match="detector load failed"):
        service._build_detector()
    with pytest.raises(RuntimeError, match="classifier load failed"):
        service._build_classifier()


def test_inference_service_records_model_init_error_without_mock_fallback(monkeypatch):
    config = load_config("pi/config/default.yaml")
    service = service_module.InferenceService.__new__(service_module.InferenceService)
    events = []
    service.config = config
    service.database = type("Database", (), {"add_device_event": lambda self, *args: events.append(args)})()

    def raise_detector_error():
        raise RuntimeError("detector load failed")

    monkeypatch.setattr(service, "_build_detector", raise_detector_error)

    service._initialize_models()

    assert service.health == "error"
    assert service.detector is None
    assert service.classifier is None
    assert "detector load failed" in service.last_error
    assert events[0][0] == "inference.model_error"


def test_ultralytics_detector_can_filter_tiny_boxes_without_loading_model():
    detector = UltralyticsSignDetector.__new__(UltralyticsSignDetector)
    detector.min_box_area = 900

    assert detector._passes_size_filter(10, 10, 39, 39) is False
    assert detector._passes_size_filter(10, 10, 40, 40) is True


def test_detector_label_classifier_allows_detector_only_mode():
    classifier = DetectorLabelClassifier()
    candidate = DetectionCandidate(
        bbox=(10, 10, 40, 40),
        detector_label="sign",
        shape_label="learned",
        color_label="unknown",
        confidence=0.42,
    )

    result = classifier.classify(np.zeros((80, 80, 3), dtype=np.uint8), candidate)

    assert result.raw_label == "sign"
    assert result.confidence == 0.42


def test_detector_prefers_centered_sign_shapes_over_noise():
    config = load_config("pi/config/mock.yaml")
    detector = MockColorShapeDetector(config.inference)
    classifier = MockSignClassifier()

    frame = np.zeros((400, 400, 3), dtype=np.uint8)

    # Border-hugging blob should be ignored by the stricter bbox filters.
    cv2.rectangle(frame, (0, 0), (90, 120), (0, 0, 255), thickness=-1)

    # Centered octagon should survive and classify as stop.
    cx, cy, radius = 240, 210, 50
    points = []
    for i in range(8):
        angle = np.deg2rad(22.5 + i * 45)
        points.append((int(cx + radius * np.cos(angle)), int(cy + radius * np.sin(angle))))
    cv2.fillPoly(frame, [np.array(points, dtype=np.int32)], (0, 0, 255))

    candidates = detector.detect(frame)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.shape_label == "octagon"
    assert candidate.confidence >= config.inference.min_detector_confidence

    classification = classifier.classify(frame, candidate)
    assert classification.raw_label == "stop"
    assert classification.confidence >= config.inference.min_classifier_confidence


def test_classifier_emits_broad_green_and_white_sign_categories():
    config = load_config("pi/config/mock.yaml")
    detector = MockColorShapeDetector(config.inference)
    classifier = MockSignClassifier()

    green_frame = np.zeros((400, 400, 3), dtype=np.uint8)
    cv2.rectangle(green_frame, (140, 140), (260, 260), (0, 180, 0), thickness=-1)
    green_candidates = detector.detect(green_frame)
    assert green_candidates
    green_label = classifier.classify(green_frame, green_candidates[0]).raw_label
    assert green_label == "guide_sign"

    white_frame = np.zeros((400, 400, 3), dtype=np.uint8)
    cv2.rectangle(white_frame, (140, 140), (260, 260), (255, 255, 255), thickness=-1)
    white_candidates = detector.detect(white_frame)
    assert white_candidates
    white_label = classifier.classify(white_frame, white_candidates[0]).raw_label
    assert white_label == "regulatory_rect"
