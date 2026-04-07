from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


def load_plan(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_workspace(plan: dict[str, Any], repo_root: Path) -> dict[str, Path]:
    workspace = plan["workspace"]
    root = repo_root / workspace["root"]
    manifest_dir = root / "manifest"
    raw_dir = root / "raw"
    prepared_dir = root / "prepared"
    exports_dir = root / "exports"
    for path in (root, manifest_dir, raw_dir, prepared_dir, exports_dir):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "manifest": manifest_dir,
        "raw": raw_dir,
        "prepared": prepared_dir,
        "exports": exports_dir,
    }


def inventory_dataset(repo_root: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    root = repo_root / dataset["local_root"]
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    annotation_exts = {".json", ".csv", ".txt"}
    image_count = 0
    annotation_count = 0
    suffix_counter: Counter[str] = Counter()

    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            suffix_counter[suffix] += 1
            if suffix in image_exts:
                image_count += 1
            if suffix in annotation_exts:
                annotation_count += 1

    expected = dataset.get("expected", {})
    return {
        "id": dataset["id"],
        "name": dataset["name"],
        "role": dataset["role"],
        "local_root": str(root),
        "present": root.exists(),
        "expected_images_dir": str(root / expected.get("images_dir", "images")),
        "expected_annotations_dir": str(root / expected.get("annotations_dir", "annotations")),
        "image_count": image_count,
        "annotation_count": annotation_count,
        "file_suffix_counts": dict(sorted(suffix_counter.items())),
        "source_url": dataset.get("source_url"),
        "notes": dataset.get("notes", []),
    }


def build_outputs(plan: dict[str, Any], repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    inventory = {
        "version": plan.get("version", 1),
        "strategy": plan["targets"]["strategy"],
        "datasets": [inventory_dataset(repo_root, dataset) for dataset in plan.get("datasets", [])],
    }
    label_schema = {
        "version": plan.get("version", 1),
        "strategy": plan["targets"]["strategy"],
        "broad_categories": plan["targets"]["broad_categories"],
    }
    return inventory, label_schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="training/datasets.yaml")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / args.config
    plan = load_plan(config_path)
    ensure_workspace(plan, repo_root)
    inventory, label_schema = build_outputs(plan, repo_root)

    inventory_output = repo_root / plan["workspace"]["inventory_output"]
    label_schema_output = repo_root / plan["workspace"]["label_schema_output"]
    inventory_output.parent.mkdir(parents=True, exist_ok=True)
    label_schema_output.parent.mkdir(parents=True, exist_ok=True)
    inventory_output.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    label_schema_output.write_text(json.dumps(label_schema, indent=2), encoding="utf-8")
    print(json.dumps({"inventory": str(inventory_output), "label_schema": str(label_schema_output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
