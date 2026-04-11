from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "export_yolo_detection_dataset.py"
SPEC = importlib.util.spec_from_file_location("export_yolo_detection_dataset", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_export_manifest_to_yolo_creates_dataset(tmp_path):
    repo_root = tmp_path
    training_dir = repo_root / "training"
    training_dir.mkdir(parents=True)
    (training_dir / "datasets.yaml").write_text(
        yaml.safe_dump({"targets": {"broad_categories": ["stop", "guide_general"]}}, sort_keys=False),
        encoding="utf-8",
    )

    image_dir = repo_root / "data/training/raw/mapillary/images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "frame_a.jpg"
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)

    manifest_path = repo_root / "data/training/prepared/unified_sign_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_id": "mapillary",
                "image_path": "data/training/raw/mapillary/images/frame_a.jpg",
                "raw_label": "stop sign",
                "broad_category": "stop",
                "bbox_xyxy": [20, 30, 120, 80],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = repo_root / "data/training/exports/yolo_broad_signs"
    summary = MODULE.export_manifest_to_yolo(
        manifest_path=manifest_path,
        output_dir=output_dir,
        repo_root=repo_root,
        categories=MODULE.load_plan_categories(training_dir / "datasets.yaml", "broad"),
        label_mode="broad",
        val_ratio=0.0,
        image_mode="copy",
    )

    assert summary["split_image_counts"]["train"] == 1
    assert summary["split_label_counts"]["train"] == 1
    label_path = output_dir / "labels/train/frame_a.txt"
    assert label_path.exists()
    assert label_path.read_text(encoding="utf-8").strip() == "0 0.350000 0.550000 0.500000 0.500000"

    dataset_yaml = yaml.safe_load((output_dir / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_yaml["train"] == "images/train"
    assert dataset_yaml["names"][0] == "stop"


def test_export_manifest_to_yolo_skips_missing_images(tmp_path):
    repo_root = tmp_path
    manifest_path = repo_root / "data/training/prepared/unified_sign_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_id": "mapillary",
                "image_path": "data/training/raw/mapillary/images/missing.jpg",
                "raw_label": "guide sign",
                "broad_category": "guide_general",
                "bbox_xyxy": [0, 0, 10, 10],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = repo_root / "data/training/exports/yolo_broad_signs"
    summary = MODULE.export_manifest_to_yolo(
        manifest_path=manifest_path,
        output_dir=output_dir,
        repo_root=repo_root,
        categories=["guide_general"],
        label_mode="broad",
        val_ratio=0.2,
        image_mode="copy",
    )

    assert summary["skipped_records"]["missing_source_image"] == 1
    assert not (output_dir / "labels/train/missing.txt").exists()


def test_export_manifest_to_yolo_any_sign_mode_collapses_classes(tmp_path):
    repo_root = tmp_path
    training_dir = repo_root / "training"
    training_dir.mkdir(parents=True)
    (training_dir / "datasets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "detector_categories": ["sign"],
                    "broad_categories": ["stop", "warning_general"],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    image_dir = repo_root / "data/training/raw/mapillary/images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "frame_any.jpg"
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)

    manifest_path = repo_root / "data/training/prepared/unified_sign_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "dataset_id": "mapillary",
                        "image_path": "data/training/raw/mapillary/images/frame_any.jpg",
                        "raw_label": "stop sign",
                        "broad_category": "stop",
                        "bbox_xyxy": [10, 10, 40, 40],
                    }
                ),
                json.dumps(
                    {
                        "dataset_id": "mapillary",
                        "image_path": "data/training/raw/mapillary/images/frame_any.jpg",
                        "raw_label": "curve warning",
                        "broad_category": "warning_general",
                        "bbox_xyxy": [50, 20, 90, 80],
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = repo_root / "data/training/exports/yolo_any_signs"
    summary = MODULE.export_manifest_to_yolo(
        manifest_path=manifest_path,
        output_dir=output_dir,
        repo_root=repo_root,
        categories=MODULE.load_plan_categories(training_dir / "datasets.yaml", "any_sign"),
        label_mode="any_sign",
        val_ratio=0.0,
        image_mode="copy",
    )

    assert summary["categories"] == ["sign"]
    assert summary["label_mode"] == "any_sign"
    label_path = output_dir / "labels/train/frame_any.txt"
    assert label_path.exists()
    label_lines = label_path.read_text(encoding="utf-8").strip().splitlines()
    assert label_lines == [
        "0 0.250000 0.250000 0.300000 0.300000",
        "0 0.700000 0.500000 0.400000 0.600000",
    ]

    dataset_yaml = yaml.safe_load((output_dir / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_yaml["names"][0] == "sign"
