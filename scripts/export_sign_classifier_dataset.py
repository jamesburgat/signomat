from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import re
from typing import Any

import cv2
import yaml


DEFAULT_TAXONOMY_PATH = "training/classifier_taxonomy_us.yaml"
DEFAULT_OUTPUT_DIR = "data/training/exports/classifier_us_signs"

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


def compile_taxonomy_classes(taxonomy_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8")) or {}
    compiled: list[dict[str, Any]] = []
    for entry in payload.get("classes", []):
        compiled.append(
            {
                "id": str(entry["id"]),
                "exact_raw_labels": tuple(str(item) for item in entry.get("exact_raw_labels", [])),
                "raw_label_prefixes": tuple(str(item) for item in entry.get("raw_label_prefixes", [])),
                "raw_label_regexes": tuple(re.compile(str(item)) for item in entry.get("raw_label_regexes", [])),
                "datasets": tuple(str(item) for item in entry.get("datasets", [])),
                "broad_categories": tuple(str(item) for item in entry.get("broad_categories", [])),
            }
        )
    return payload, compiled


def matches_class_rule(record: dict[str, Any], rule: dict[str, Any]) -> bool:
    raw_label = str(record.get("raw_label") or "")
    dataset_id = str(record.get("dataset_id") or "")
    broad_category = str(record.get("broad_category") or "")

    if rule["datasets"] and dataset_id not in rule["datasets"]:
        return False
    if rule["broad_categories"] and broad_category not in rule["broad_categories"]:
        return False
    if rule["exact_raw_labels"] and raw_label in rule["exact_raw_labels"]:
        return True
    if rule["raw_label_prefixes"] and any(raw_label.startswith(prefix) for prefix in rule["raw_label_prefixes"]):
        return True
    if rule["raw_label_regexes"] and any(pattern.search(raw_label) for pattern in rule["raw_label_regexes"]):
        return True
    return False


def map_record_to_classifier_label(record: dict[str, Any], rules: list[dict[str, Any]]) -> str | None:
    for rule in rules:
        if matches_class_rule(record, rule):
            return str(rule["id"])
    return None


def split_name_for_path(path: str, val_ratio: float) -> str:
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_ratio else "train"


def clamp_crop_bounds(
    bbox_xyxy: list[float],
    width: int,
    height: int,
    pad_ratio: float,
) -> tuple[int, int, int, int] | None:
    if width <= 0 or height <= 0 or len(bbox_xyxy) != 4:
        return None
    x1, y1, x2, y2 = [float(value) for value in bbox_xyxy]
    if x2 <= x1 or y2 <= y1:
        return None
    pad_x = (x2 - x1) * pad_ratio
    pad_y = (y2 - y1) * pad_ratio
    left = max(0, int(round(x1 - pad_x)))
    top = max(0, int(round(y1 - pad_y)))
    right = min(width, int(round(x2 + pad_x)))
    bottom = min(height, int(round(y2 + pad_y)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def crop_filename(record: dict[str, Any], class_id: str) -> str:
    image_path = str(record.get("image_path") or "unknown")
    bbox = record.get("bbox_xyxy") or []
    digest_source = json.dumps(
        {
            "image_path": image_path,
            "bbox_xyxy": bbox,
            "raw_label": record.get("raw_label"),
            "class_id": class_id,
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    stem = Path(image_path).stem or "crop"
    return f"{stem}_{digest}.jpg"


def build_mapped_records(
    manifest_path: Path,
    repo_root: Path,
    rules: list[dict[str, Any]],
    val_ratio: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    skipped = Counter()
    class_counts = Counter()
    dataset_counts = Counter()

    for record in load_manifest_records(manifest_path):
        image_path_value = record.get("image_path")
        bbox_xyxy = record.get("bbox_xyxy")
        if not image_path_value:
            skipped["missing_image_path"] += 1
            continue
        if bbox_xyxy is None:
            skipped["missing_bbox"] += 1
            continue
        class_id = map_record_to_classifier_label(record, rules)
        if class_id is None:
            skipped["unmapped_label"] += 1
            continue
        image_path = repo_root / str(image_path_value)
        mapped_record = dict(record)
        mapped_record["classifier_label"] = class_id
        mapped_record["split"] = split_name_for_path(str(image_path), val_ratio)
        mapped_record["resolved_image_path"] = str(image_path)
        mapped.append(mapped_record)
        class_counts[class_id] += 1
        dataset_counts[str(record.get("dataset_id") or "unknown")] += 1

    summary = {
        "mapped_record_count": len(mapped),
        "class_counts": dict(sorted(class_counts.items())),
        "dataset_counts": dict(sorted(dataset_counts.items())),
        "skipped_records": dict(skipped),
    }
    return mapped, summary


def export_classifier_dataset(
    manifest_path: Path,
    taxonomy_path: Path,
    output_dir: Path,
    repo_root: Path,
    val_ratio: float,
    pad_ratio: float,
    min_crop_size: int,
    image_quality: int,
    summary_only: bool,
) -> dict[str, Any]:
    taxonomy_payload, rules = compile_taxonomy_classes(taxonomy_path)
    mapped_records, mapping_summary = build_mapped_records(manifest_path, repo_root, rules, val_ratio)
    all_class_ids = [str(rule["id"]) for rule in rules]
    active_class_ids = [class_id for class_id in all_class_ids if mapping_summary["class_counts"].get(class_id, 0) > 0]

    summary: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "taxonomy_path": str(taxonomy_path),
        "taxonomy_name": taxonomy_payload.get("name"),
        "output_dir": str(output_dir),
        "summary_only": summary_only,
        "val_ratio": val_ratio,
        "pad_ratio": pad_ratio,
        "min_crop_size": min_crop_size,
        "class_ids": all_class_ids,
        "active_class_ids": active_class_ids,
        **mapping_summary,
    }

    if summary_only:
        return summary

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val"):
        for class_id in active_class_ids:
            (output_dir / split / class_id).mkdir(parents=True, exist_ok=True)

    grouped_records: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for record in mapped_records:
        grouped_records[Path(record["resolved_image_path"])].append(record)

    crop_manifest_path = output_dir / "crop_manifest.jsonl"
    crop_manifest_entries: list[str] = []
    exported_class_counts = Counter()
    exported_split_counts = Counter()
    export_skipped = Counter(summary["skipped_records"])

    for image_path, records in sorted(grouped_records.items()):
        if not image_path.exists():
            export_skipped["missing_source_image"] += len(records)
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            export_skipped["unreadable_image"] += len(records)
            continue
        height, width = image.shape[:2]

        for record in records:
            bounds = clamp_crop_bounds(record["bbox_xyxy"], width, height, pad_ratio)
            if bounds is None:
                export_skipped["invalid_bbox"] += 1
                continue
            left, top, right, bottom = bounds
            if (right - left) < min_crop_size or (bottom - top) < min_crop_size:
                export_skipped["too_small_crop"] += 1
                continue

            crop = image[top:bottom, left:right]
            if crop.size == 0:
                export_skipped["empty_crop"] += 1
                continue

            class_id = str(record["classifier_label"])
            split = str(record["split"])
            crop_path = output_dir / split / class_id / crop_filename(record, class_id)
            success = cv2.imwrite(str(crop_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), image_quality])
            if not success:
                export_skipped["failed_crop_write"] += 1
                continue

            exported_class_counts[class_id] += 1
            exported_split_counts[split] += 1
            crop_manifest_entries.append(
                json.dumps(
                    {
                        "crop_path": str(crop_path.relative_to(output_dir)),
                        "split": split,
                        "classifier_label": class_id,
                        "raw_label": record["raw_label"],
                        "dataset_id": record["dataset_id"],
                        "image_path": record["image_path"],
                        "bbox_xyxy": record["bbox_xyxy"],
                        "crop_xyxy": [left, top, right, bottom],
                    }
                )
            )

    crop_manifest_path.write_text("\n".join(crop_manifest_entries) + ("\n" if crop_manifest_entries else ""), encoding="utf-8")
    dataset_yaml = {
        "path": str(output_dir.resolve()),
        "train": "train",
        "val": "val",
        "names": {index: class_id for index, class_id in enumerate(active_class_ids)},
    }
    (output_dir / "dataset.yaml").write_text(yaml.safe_dump(dataset_yaml, sort_keys=False), encoding="utf-8")

    summary["exported_class_counts"] = dict(sorted(exported_class_counts.items()))
    summary["exported_split_counts"] = dict(sorted(exported_split_counts.items()))
    summary["skipped_records"] = dict(export_skipped)
    (output_dir / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export cropped sign images for classifier training.")
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "data/training/prepared/unified_sign_manifest.jsonl",
        help="Path to the normalized manifest JSONL.",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=repo_root / DEFAULT_TAXONOMY_PATH,
        help="YAML taxonomy defining classifier classes and raw-label matches.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / DEFAULT_OUTPUT_DIR,
        help="Directory to write classifier crops into.",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.2,
        help="Fraction of source images assigned to validation.",
    )
    parser.add_argument(
        "--pad-ratio",
        type=float,
        default=0.08,
        help="Extra crop padding added to each side as a fraction of box width/height.",
    )
    parser.add_argument(
        "--min-crop-size",
        type=int,
        default=24,
        help="Minimum crop width/height in pixels after padding.",
    )
    parser.add_argument(
        "--image-quality",
        type=int,
        default=95,
        help="JPEG quality for saved crops.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print mapped class counts without writing crops.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    summary = export_classifier_dataset(
        manifest_path=args.manifest,
        taxonomy_path=args.taxonomy,
        output_dir=args.output_dir,
        repo_root=repo_root,
        val_ratio=args.val_ratio,
        pad_ratio=args.pad_ratio,
        min_crop_size=args.min_crop_size,
        image_quality=args.image_quality,
        summary_only=args.summary_only,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
