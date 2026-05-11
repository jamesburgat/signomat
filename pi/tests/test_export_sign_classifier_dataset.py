from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "export_sign_classifier_dataset.py"
SPEC = importlib.util.spec_from_file_location("export_sign_classifier_dataset", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_map_record_to_classifier_label_supports_exact_prefix_and_regex(tmp_path):
    taxonomy_path = tmp_path / "taxonomy.yaml"
    taxonomy_path.write_text(
        yaml.safe_dump(
            {
                "classes": [
                    {"id": "stop", "exact_raw_labels": ["regulatory--stop--g1"]},
                    {"id": "keep_right", "raw_label_prefixes": ["regulatory--keep-right--"]},
                    {"id": "speed_limit_45", "raw_label_regexes": [r"^regulatory--maximum-speed-limit-45--"]},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _, rules = MODULE.compile_taxonomy_classes(taxonomy_path)

    assert MODULE.map_record_to_classifier_label({"raw_label": "regulatory--stop--g1"}, rules) == "stop"
    assert MODULE.map_record_to_classifier_label({"raw_label": "regulatory--keep-right--g4"}, rules) == "keep_right"
    assert (
        MODULE.map_record_to_classifier_label({"raw_label": "regulatory--maximum-speed-limit-45--g3"}, rules)
        == "speed_limit_45"
    )
    assert MODULE.map_record_to_classifier_label({"raw_label": "other-sign"}, rules) is None


def test_export_classifier_dataset_writes_crops_and_summary(tmp_path):
    repo_root = tmp_path
    image_dir = repo_root / "data/training/raw/mapillary/images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "frame_a.jpg"
    image = np.zeros((100, 120, 3), dtype=np.uint8)
    image[:, :60] = (0, 0, 255)
    image[:, 60:] = (0, 255, 0)
    assert cv2.imwrite(str(image_path), image)

    manifest_path = repo_root / "data/training/prepared/unified_sign_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "dataset_id": "mapillary",
                        "image_path": "data/training/raw/mapillary/images/frame_a.jpg",
                        "raw_label": "regulatory--stop--g1",
                        "broad_category": "stop",
                        "bbox_xyxy": [10, 10, 50, 70],
                    }
                ),
                json.dumps(
                    {
                        "dataset_id": "mapillary",
                        "image_path": "data/training/raw/mapillary/images/frame_a.jpg",
                        "raw_label": "regulatory--maximum-speed-limit-45--g3",
                        "broad_category": "speed_limit",
                        "bbox_xyxy": [70, 15, 110, 75],
                    }
                ),
                json.dumps(
                    {
                        "dataset_id": "mapillary",
                        "image_path": "data/training/raw/mapillary/images/frame_a.jpg",
                        "raw_label": "other-sign",
                        "broad_category": "other_sign_like",
                        "bbox_xyxy": [0, 0, 20, 20],
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    taxonomy_path = repo_root / "training/classifier_taxonomy_us.yaml"
    taxonomy_path.parent.mkdir(parents=True)
    taxonomy_path.write_text(
        yaml.safe_dump(
            {
                "name": "test_taxonomy",
                "classes": [
                    {"id": "stop", "exact_raw_labels": ["regulatory--stop--g1"]},
                    {"id": "speed_limit_45", "raw_label_regexes": [r"^regulatory--maximum-speed-limit-45--"]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    output_dir = repo_root / "data/training/exports/classifier_us_signs"
    summary = MODULE.export_classifier_dataset(
        manifest_path=manifest_path,
        taxonomy_path=taxonomy_path,
        output_dir=output_dir,
        repo_root=repo_root,
        val_ratio=0.0,
        pad_ratio=0.0,
        min_crop_size=10,
        image_quality=95,
        summary_only=False,
    )

    assert summary["mapped_record_count"] == 2
    assert summary["skipped_records"]["unmapped_label"] == 1
    assert summary["exported_class_counts"] == {"speed_limit_45": 1, "stop": 1}
    assert summary["exported_split_counts"] == {"train": 2}

    stop_dir = output_dir / "train/stop"
    speed_dir = output_dir / "train/speed_limit_45"
    assert len(list(stop_dir.glob("*.jpg"))) == 1
    assert len(list(speed_dir.glob("*.jpg"))) == 1

    crop_manifest = (output_dir / "crop_manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(crop_manifest) == 2

    dataset_yaml = yaml.safe_load((output_dir / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_yaml["train"] == "train"
    assert dataset_yaml["names"][0] == "stop"


def test_export_archive_classifier_dataset_uses_sign_crops_and_frame_fallback(tmp_path):
    crop_image = np.zeros((48, 48, 3), dtype=np.uint8)
    crop_image[:, :] = (0, 0, 255)
    crop_path = tmp_path / "sign_crop.jpg"
    assert cv2.imwrite(str(crop_path), crop_image)

    frame_image = np.zeros((100, 120, 3), dtype=np.uint8)
    frame_image[20:80, 50:110] = (0, 255, 0)
    frame_path = tmp_path / "clean_frame.jpg"
    assert cv2.imwrite(str(frame_path), frame_image)

    payload = {
        "detections": [
            {
                "eventId": "evt_crop",
                "tripId": "trip_a",
                "reviewState": "reviewed",
                "specificLabel": "stop_sign",
                "categoryLabel": "stop",
                "signCropUrl": crop_path.as_uri(),
            },
            {
                "eventId": "evt_frame",
                "tripId": "trip_a",
                "reviewState": "reviewed",
                "specificLabel": "speed_limit_35",
                "categoryLabel": "speed_limit",
                "cleanFrameUrl": frame_path.as_uri(),
                "bboxLeft": 50,
                "bboxTop": 20,
                "bboxRight": 110,
                "bboxBottom": 80,
            },
            {
                "eventId": "evt_negative",
                "tripId": "trip_a",
                "reviewState": "false_positive",
                "categoryLabel": "not_a_sign",
                "signCropUrl": crop_path.as_uri(),
            },
        ]
    }

    output_dir = tmp_path / "archive_classifier_export"
    summary = MODULE.export_archive_classifier_dataset(
        payload=payload,
        source_label="unit-test",
        output_dir=output_dir,
        val_ratio=0.0,
        pad_ratio=0.0,
        min_crop_size=24,
        image_quality=95,
        summary_only=False,
        cache_dir=tmp_path / "cache",
        timeout_seconds=5.0,
        label_source="specific_or_category",
    )

    assert summary["candidate_record_count"] == 2
    assert summary["exported_class_counts"] == {"speed_limit_35": 1, "stop_sign": 1}
    assert summary["exported_split_counts"] == {"train": 2}
    assert summary["skipped_records"]["review_state_false_positive"] == 1

    stop_dir = output_dir / "train/stop_sign"
    speed_dir = output_dir / "train/speed_limit_35"
    assert len(list(stop_dir.glob("*.jpg"))) == 1
    assert len(list(speed_dir.glob("*.jpg"))) == 1

    crop_manifest = [json.loads(line) for line in (output_dir / "crop_manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(crop_manifest) == 2
    assert any(entry["used_sign_crop_asset"] is True for entry in crop_manifest)
    assert any(entry["used_sign_crop_asset"] is False for entry in crop_manifest)

    dataset_yaml = yaml.safe_load((output_dir / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_yaml["train"] == "train"
