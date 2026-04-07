from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import yaml


DEFAULT_BROAD_CATEGORIES = (
    "stop",
    "yield",
    "speed_limit",
    "regulatory_general",
    "warning_general",
    "crossing",
    "work_zone_general",
    "guide_general",
    "service_general",
    "text_rectangular_general",
    "other_sign_like",
    "unknown_sign",
)


def load_plan_categories(plan_path: Path) -> list[str]:
    if not plan_path.exists():
        return list(DEFAULT_BROAD_CATEGORIES)
    payload = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    categories = payload.get("targets", {}).get("broad_categories")
    if not categories:
        return list(DEFAULT_BROAD_CATEGORIES)
    return [str(item) for item in categories]


def load_manifest_records(manifest_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not manifest_path.exists():
        return records
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def bbox_xyxy_to_yolo(bbox_xyxy: list[float], width: int, height: int) -> tuple[float, float, float, float] | None:
    if width <= 0 or height <= 0 or len(bbox_xyxy) != 4:
        return None
    x1, y1, x2, y2 = [float(value) for value in bbox_xyxy]
    x1 = max(0.0, min(x1, float(width)))
    y1 = max(0.0, min(y1, float(height)))
    x2 = max(0.0, min(x2, float(width)))
    y2 = max(0.0, min(y2, float(height)))
    if x2 <= x1 or y2 <= y1:
        return None
    box_width = x2 - x1
    box_height = y2 - y1
    center_x = x1 + (box_width / 2.0)
    center_y = y1 + (box_height / 2.0)
    return (
        center_x / float(width),
        center_y / float(height),
        box_width / float(width),
        box_height / float(height),
    )


def split_name_for_path(path: str, val_ratio: float) -> str:
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_ratio else "train"


def link_or_copy_image(source: Path, destination: Path, mode: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    if mode == "copy":
        shutil.copy2(source, destination)
        return
    destination.symlink_to(source)


def image_size(path: Path) -> tuple[int, int] | None:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    height, width = image.shape[:2]
    return width, height


def export_manifest_to_yolo(
    manifest_path: Path,
    output_dir: Path,
    repo_root: Path,
    categories: list[str],
    val_ratio: float,
    image_mode: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    labels_dir = output_dir / "labels"
    for split in ("train", "val"):
        (images_dir / split).mkdir(parents=True, exist_ok=True)
        (labels_dir / split).mkdir(parents=True, exist_ok=True)

    class_ids = {name: index for index, name in enumerate(categories)}
    grouped_records: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()

    for record in load_manifest_records(manifest_path):
        image_path_value = record.get("image_path")
        category = record.get("broad_category")
        bbox = record.get("bbox_xyxy")
        if not image_path_value:
            skipped["missing_image_path"] += 1
            continue
        if category not in class_ids:
            skipped["unknown_category"] += 1
            continue
        if bbox is None:
            skipped["missing_bbox"] += 1
            continue
        image_path = repo_root / str(image_path_value)
        grouped_records[image_path].append(record)

    split_image_counts = Counter()
    split_label_counts = Counter()

    for image_path, records in sorted(grouped_records.items()):
        if not image_path.exists():
            skipped["missing_source_image"] += len(records)
            continue
        size = image_size(image_path)
        if size is None:
            skipped["unreadable_image"] += len(records)
            continue
        width, height = size
        split = split_name_for_path(str(image_path), val_ratio)
        destination_image = images_dir / split / image_path.name
        destination_label = labels_dir / split / f"{image_path.stem}.txt"

        label_lines: list[str] = []
        for record in records:
            yolo_box = bbox_xyxy_to_yolo(record["bbox_xyxy"], width, height)
            if yolo_box is None:
                skipped["invalid_bbox"] += 1
                continue
            class_id = class_ids[record["broad_category"]]
            x_center, y_center, box_width, box_height = yolo_box
            label_lines.append(
                f"{class_id} {x_center:.6f} {y_center:.6f} {box_width:.6f} {box_height:.6f}"
            )
            split_label_counts[split] += 1

        if not label_lines:
            skipped["images_without_valid_labels"] += 1
            continue

        link_or_copy_image(image_path, destination_image, image_mode)
        destination_label.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
        split_image_counts[split] += 1

    dataset_yaml = {
        "path": str(output_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "names": {index: name for index, name in enumerate(categories)},
    }
    (output_dir / "dataset.yaml").write_text(yaml.safe_dump(dataset_yaml, sort_keys=False), encoding="utf-8")

    summary = {
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir),
        "image_mode": image_mode,
        "val_ratio": val_ratio,
        "categories": categories,
        "split_image_counts": dict(split_image_counts),
        "split_label_counts": dict(split_label_counts),
        "skipped_records": dict(skipped),
    }
    (output_dir / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the unified sign manifest to a YOLO detection dataset.")
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "data/training/prepared/unified_sign_manifest.jsonl",
        help="Path to the normalized manifest JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "data/training/exports/yolo_broad_signs",
        help="Directory to write the YOLO dataset into.",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=repo_root / "training/datasets.yaml",
        help="Dataset plan used to define class ordering.",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.2,
        help="Fraction of images assigned to the validation split.",
    )
    parser.add_argument(
        "--image-mode",
        choices=("symlink", "copy"),
        default="symlink",
        help="Whether to symlink or copy source images into the YOLO export.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    categories = load_plan_categories(args.plan)
    summary = export_manifest_to_yolo(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        repo_root=repo_root,
        categories=categories,
        val_ratio=args.val_ratio,
        image_mode=args.image_mode,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
