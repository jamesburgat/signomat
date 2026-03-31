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
