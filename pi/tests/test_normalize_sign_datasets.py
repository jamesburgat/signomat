from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "normalize_sign_datasets.py"
SPEC = importlib.util.spec_from_file_location("normalize_sign_datasets", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_map_to_broad_category_covers_new_targets():
    assert MODULE.map_to_broad_category("guide sign") == "guide_general"
    assert MODULE.map_to_broad_category("speed limit 45") == "speed_limit"
    assert MODULE.map_to_broad_category("work zone") == "work_zone_general"
    assert MODULE.map_to_broad_category("service blue sign") == "service_general"


def test_normalize_dataset_parses_coco_csv_and_xml(tmp_path):
    repo_root = tmp_path

    dataset_root = repo_root / "data/training/raw/mapillary"
    images_dir = dataset_root / "images"
    annotations_dir = dataset_root / "annotations"
    images_dir.mkdir(parents=True)
    annotations_dir.mkdir(parents=True)
    (images_dir / "frame_a.jpg").write_bytes(b"")
    (annotations_dir / "instances.json").write_text(
        json.dumps(
            {
                "images": [{"id": 1, "file_name": "frame_a.jpg"}],
                "categories": [{"id": 5, "name": "guide sign"}],
                "annotations": [{"id": 9, "image_id": 1, "category_id": 5, "bbox": [10, 20, 30, 40]}],
            }
        ),
        encoding="utf-8",
    )

    dataset = {
        "id": "mapillary",
        "name": "Mapillary Traffic Sign Dataset",
        "local_root": "data/training/raw/mapillary",
        "expected": {"images_dir": "images", "annotations_dir": "annotations"},
    }
    records, summary = MODULE.normalize_dataset(repo_root, dataset)
    assert summary["record_count"] == 1
    assert records[0]["broad_category"] == "guide_general"
    assert records[0]["bbox_xyxy"] == [10.0, 20.0, 40.0, 60.0]

    glare_csv_root = repo_root / "data/training/raw/glare_csv"
    glare_csv_images = glare_csv_root / "images"
    glare_csv_annotations = glare_csv_root / "annotations"
    glare_csv_images.mkdir(parents=True)
    glare_csv_annotations.mkdir(parents=True)
    (glare_csv_images / "frame_b.jpg").write_bytes(b"")
    (glare_csv_annotations / "annotations.csv").write_text(
        "filename,Annotation tag,Upper left corner X,Upper left corner Y,Lower right corner X,Lower right corner Y\n"
        "frame_b.jpg,stop,1,2,3,4\n",
        encoding="utf-8",
    )
    glare_csv_dataset = {
        "id": "glare_csv",
        "name": "GLARE CSV",
        "local_root": "data/training/raw/glare_csv",
        "expected": {"images_dir": "images", "annotations_dir": "annotations"},
    }
    glare_csv_records, _ = MODULE.normalize_dataset(repo_root, glare_csv_dataset)
    assert glare_csv_records[0]["broad_category"] == "stop"

    glare_root = repo_root / "data/training/raw/glare"
    glare_images = glare_root / "images"
    glare_annotations = glare_root / "annotations"
    glare_images.mkdir(parents=True)
    glare_annotations.mkdir(parents=True)
    (glare_images / "frame_c.jpg").write_bytes(b"")
    (glare_annotations / "frame_c.xml").write_text(
        "<annotation><filename>frame_c.jpg</filename><object><name>work zone</name><bndbox><xmin>5</xmin><ymin>6</ymin><xmax>7</xmax><ymax>8</ymax></bndbox></object></annotation>",
        encoding="utf-8",
    )
    glare_dataset = {
        "id": "glare",
        "name": "GLARE",
        "local_root": "data/training/raw/glare",
        "expected": {"images_dir": "images", "annotations_dir": "annotations"},
    }
    glare_records, _ = MODULE.normalize_dataset(repo_root, glare_dataset)
    assert glare_records[0]["broad_category"] == "work_zone_general"


def test_normalize_all_builds_summary(tmp_path):
    repo_root = tmp_path
    training_dir = repo_root / "training"
    training_dir.mkdir(parents=True)
    plan = {
        "version": 1,
        "workspace": {"root": "data/training"},
        "targets": {
            "strategy": "detect_any_sign_then_sort",
            "detector_categories": ["sign"],
            "broad_categories": list(MODULE.BROAD_CATEGORIES),
        },
        "datasets": [
            {
                "id": "mapillary",
                "name": "Mapillary Traffic Sign Dataset",
                "local_root": "data/training/raw/mapillary",
                "expected": {"images_dir": "images", "annotations_dir": "annotations"},
            }
        ],
    }
    images = repo_root / "data/training/raw/mapillary/images"
    annotations = repo_root / "data/training/raw/mapillary/annotations"
    images.mkdir(parents=True)
    annotations.mkdir(parents=True)
    (images / "frame.jpg").write_bytes(b"")
    (annotations / "instances.json").write_text(
        json.dumps(
            {
                "images": [{"id": 1, "file_name": "frame.jpg"}],
                "categories": [{"id": 1, "name": "speed limit 45"}],
                "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10]}],
            }
        ),
        encoding="utf-8",
    )

    records, summary = MODULE.normalize_all(plan, repo_root)

    assert len(records) == 1
    assert summary["total_records"] == 1
    assert summary["overall_broad_category_counts"]["speed_limit"] == 1


def test_normalize_dataset_supports_mtsd_json(tmp_path):
    repo_root = tmp_path

    dataset_root = repo_root / "data/training/raw/mapillary"
    images_dir = dataset_root / "images" / "part_01"
    annotations_dir = dataset_root / "annotations" / "fully"
    images_dir.mkdir(parents=True)
    annotations_dir.mkdir(parents=True)
    (images_dir / "abc123.jpg").write_bytes(b"")
    (annotations_dir / "abc123.json").write_text(
        json.dumps(
            {
                "width": 1280,
                "height": 720,
                "objects": [
                    {
                        "label": "regulatory--stop--g1",
                        "bbox": {"xmin": 10, "ymin": 20, "xmax": 30, "ymax": 40},
                        "properties": {"dummy": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    dataset = {
        "id": "mapillary",
        "name": "Mapillary Traffic Sign Dataset",
        "local_root": "data/training/raw/mapillary",
        "expected": {"images_dir": "images", "annotations_dir": "annotations"},
    }
    records, summary = MODULE.normalize_dataset(repo_root, dataset)

    assert summary["record_count"] == 1
    assert summary["parser_counts"]["mtsd_json"] == 1
    assert records[0]["broad_category"] == "stop"
    assert records[0]["image_path"] == "data/training/raw/mapillary/images/part_01/abc123.jpg"


def test_normalize_dataset_resolves_nested_csv_images(tmp_path):
    repo_root = tmp_path

    dataset_root = repo_root / "data/training/raw/glare"
    images_dir = dataset_root / "images" / "GLARE_2" / "vid0" / "clip_annotations"
    annotations_dir = dataset_root / "annotations"
    images_dir.mkdir(parents=True)
    annotations_dir.mkdir(parents=True)
    (images_dir / "frame_001.png").write_bytes(b"")
    (annotations_dir / "clip.csv").write_text(
        "Filename,Annotation tag,Upper left corner X,Upper left corner Y,Lower right corner X,Lower right corner Y\n"
        "frame_001.png,workersAhead,1,2,3,4\n",
        encoding="utf-8",
    )

    dataset = {
        "id": "glare",
        "name": "GLARE",
        "local_root": "data/training/raw/glare",
        "expected": {"images_dir": "images", "annotations_dir": "annotations"},
    }
    records, summary = MODULE.normalize_dataset(repo_root, dataset)

    assert summary["record_count"] == 1
    assert records[0]["broad_category"] == "work_zone_general"
    assert records[0]["image_path"] == "data/training/raw/glare/images/GLARE_2/vid0/clip_annotations/frame_001.png"
