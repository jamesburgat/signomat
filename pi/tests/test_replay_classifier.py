from pathlib import Path

from signomat_pi.common.config import load_config
from signomat_pi.inference_service.pipeline import DetectorLabelClassifier
from signomat_pi.inference_service.replay import _build_replay_classifier


def test_replay_classifier_uses_yolo_model_when_live_classifier_backend_is_none(monkeypatch):
    config = load_config("pi/config/default.yaml")
    config.inference.classifier_backend = "none"
    config.inference.classifier_model_path = "models/sign_classifier_yolo11n_raw_min100_ncnn_model"

    captured = {}

    class StubReplayClassifier:
        def __init__(self, *, model_path: Path, imgsz: int, verbose: bool) -> None:
            captured["model_path"] = model_path
            captured["imgsz"] = imgsz
            captured["verbose"] = verbose

    monkeypatch.setattr("signomat_pi.inference_service.replay.UltralyticsCropClassifier", StubReplayClassifier)

    classifier = _build_replay_classifier(config)

    assert isinstance(classifier, StubReplayClassifier)
    assert captured["model_path"].name == "sign_classifier_yolo11n_raw_min100_ncnn_model"
    assert captured["imgsz"] == config.inference.classifier_imgsz


def test_replay_classifier_falls_back_to_detector_label_when_model_is_missing():
    config = load_config("pi/config/default.yaml")
    config.inference.classifier_backend = "none"
    config.inference.classifier_model_path = "models/does_not_exist"

    classifier = _build_replay_classifier(config)

    assert isinstance(classifier, DetectorLabelClassifier)
