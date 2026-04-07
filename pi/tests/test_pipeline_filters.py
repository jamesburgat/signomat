import cv2
import numpy as np

from signomat_pi.common.config import load_config
from signomat_pi.inference_service.pipeline import ColorShapeCandidateDetector, HeuristicSignClassifier


def test_detector_prefers_centered_sign_shapes_over_noise():
    config = load_config("pi/config/mock.yaml")
    detector = ColorShapeCandidateDetector(config.inference)
    classifier = HeuristicSignClassifier()

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
    detector = ColorShapeCandidateDetector(config.inference)
    classifier = HeuristicSignClassifier()

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
