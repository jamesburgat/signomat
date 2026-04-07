from __future__ import annotations

import json
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "prepare_sign_training_workspace.py"
SPEC = importlib.util.spec_from_file_location("prepare_sign_training_workspace", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_training_plan_builds_inventory_and_label_schema():
    repo_root = Path(__file__).resolve().parents[2]
    plan = MODULE.load_plan(repo_root / "training/datasets.yaml")

    inventory, label_schema = MODULE.build_outputs(plan, repo_root)

    assert inventory["strategy"] == "broad_first_detection_then_sort"
    assert {item["id"] for item in inventory["datasets"]} == {"mapillary", "lisa", "glare"}
    assert "guide_general" in label_schema["broad_categories"]
    assert "unknown_sign" in label_schema["broad_categories"]


def test_training_inventory_entries_include_expected_paths():
    repo_root = Path(__file__).resolve().parents[2]
    plan = MODULE.load_plan(repo_root / "training/datasets.yaml")

    inventory, _ = MODULE.build_outputs(plan, repo_root)
    mapillary = next(item for item in inventory["datasets"] if item["id"] == "mapillary")

    assert mapillary["expected_images_dir"].endswith("data/training/raw/mapillary/images")
    assert mapillary["expected_annotations_dir"].endswith("data/training/raw/mapillary/annotations")
    json.dumps(inventory)
