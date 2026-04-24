from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
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
DEFAULT_DETECTOR_CATEGORIES = ("sign",)


def load_plan_categories(plan_path: Path, label_mode: str) -> list[str]:
    if not plan_path.exists():
        if label_mode == "any_sign":
            return list(DEFAULT_DETECTOR_CATEGORIES)
        return list(DEFAULT_BROAD_CATEGORIES)
    payload = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    targets = payload.get("targets", {})
    if label_mode == "any_sign":
        categories = targets.get("detector_categories")
        if not categories:
            return list(DEFAULT_DETECTOR_CATEGORIES)
        return [str(item) for item in categories]
    categories = targets.get("broad_categories")
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


def category_for_export(record: dict[str, Any], label_mode: str) -> str | None:
    if label_mode == "any_sign":
        return DEFAULT_DETECTOR_CATEGORIES[0]
    category = record.get("broad_category")
    if category is None:
        return None
    return str(category)


def export_manifest_to_yolo(
    manifest_path: Path,
    output_dir: Path,
    repo_root: Path,
    categories: list[str],
    label_mode: str,
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
        category = category_for_export(record, label_mode)
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
            category = category_for_export(record, label_mode)
            if category is None or category not in class_ids:
                skipped["unknown_category"] += 1
                continue
            class_id = class_ids[category]
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
        "source": "normalized_manifest",
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir),
        "label_mode": label_mode,
        "image_mode": image_mode,
        "val_ratio": val_ratio,
        "categories": categories,
        "split_image_counts": dict(split_image_counts),
        "split_label_counts": dict(split_label_counts),
        "skipped_records": dict(skipped),
    }
    (output_dir / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def load_archive_export(archive_export: Path | None, archive_export_url: str | None, timeout_seconds: float) -> tuple[dict[str, Any], str]:
    if archive_export and archive_export_url:
        raise SystemExit("Use either --archive-export or --archive-export-url, not both.")
    if archive_export:
        return json.loads(archive_export.read_text(encoding="utf-8")), str(archive_export)
    if archive_export_url:
        request = urllib.request.Request(archive_export_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8")), archive_export_url
    raise SystemExit("Archive export mode requires --archive-export or --archive-export-url.")


def local_path_from_source(source: str) -> Path | None:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("", None):
        return Path(source)
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(parsed.path))
    return None


def suffix_for_source(source: str, content_type: str | None = None) -> str:
    parsed = urllib.parse.urlparse(source)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    return ".jpg"


def cache_archive_image(source: str, cache_dir: Path, timeout_seconds: float) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_path_from_source(source)
    if local_path is not None:
        if not local_path.exists():
            raise FileNotFoundError(f"archive image source does not exist: {local_path}")
        return local_path.resolve()

    request = urllib.request.Request(source, headers={"User-Agent": "signomat-archive-export/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            suffix = suffix_for_source(source, content_type)
            digest = hashlib.sha1(source.encode("utf-8")).hexdigest()
            target = cache_dir / f"{digest}{suffix}"
            if target.exists():
                return target
            payload = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to download archive image: {source} ({exc})") from exc

    target.write_bytes(payload)
    return target


def archive_detection_bbox(record: dict[str, Any]) -> list[float] | None:
    keys = ("bboxLeft", "bboxTop", "bboxRight", "bboxBottom")
    if not all(record.get(key) is not None for key in keys):
        return None
    return [float(record[key]) for key in keys]


def archive_category_for_export(record: dict[str, Any], label_mode: str) -> str | None:
    if label_mode == "any_sign":
        return DEFAULT_DETECTOR_CATEGORIES[0]
    category = record.get("categoryLabel")
    if category is None:
        return None
    return str(category)


def archive_image_source(record: dict[str, Any]) -> str | None:
    for key in ("cleanFrameUrl", "annotatedFrameUrl", "signCropUrl"):
        value = record.get(key)
        if value:
            return str(value)
    return None


def archive_image_name(source_path: Path, records: list[dict[str, Any]]) -> str:
    if records:
        event_id = str(records[0].get("eventId") or source_path.stem)
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in event_id)
        return f"{safe_id}{source_path.suffix.lower() or '.jpg'}"
    return source_path.name


def export_archive_to_yolo(
    payload: dict[str, Any],
    source_label: str,
    output_dir: Path,
    categories: list[str],
    label_mode: str,
    val_ratio: float,
    image_mode: str,
    cache_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    labels_dir = output_dir / "labels"
    for split in ("train", "val"):
        (images_dir / split).mkdir(parents=True, exist_ok=True)
        (labels_dir / split).mkdir(parents=True, exist_ok=True)

    detections = payload.get("detections") or []
    if not isinstance(detections, list):
        raise SystemExit("Archive export JSON must contain a top-level detections list.")

    class_ids = {name: index for index, name in enumerate(categories)}
    grouped_records: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()

    for record in detections:
        if not isinstance(record, dict):
            skipped["non_object_detection_records"] += 1
            continue
        source = archive_image_source(record)
        if not source:
            skipped["missing_archive_image_url"] += 1
            continue
        try:
            image_path = cache_archive_image(str(source), cache_dir=cache_dir, timeout_seconds=timeout_seconds)
        except Exception:
            skipped["failed_archive_image_download"] += 1
            continue
        grouped_records[image_path].append(record)

    split_image_counts = Counter()
    split_label_counts = Counter()
    positive_image_counts = Counter()
    negative_image_counts = Counter()
    review_state_counts = Counter()

    for image_path, records in sorted(grouped_records.items()):
        size = image_size(image_path)
        if size is None:
            skipped["unreadable_cached_image"] += len(records)
            continue
        width, height = size
        split = split_name_for_path(str(image_path), val_ratio)
        image_name = archive_image_name(image_path, records)
        destination_image = images_dir / split / image_name
        destination_label = labels_dir / split / f"{Path(image_name).stem}.txt"

        label_lines: list[str] = []
        has_negative_only_record = False
        has_exportable_record = False
        for record in records:
            review_state = str(record.get("reviewState") or "reviewed")
            review_state_counts[review_state] += 1
            if review_state == "false_positive":
                has_negative_only_record = True
                has_exportable_record = True
                continue
            bbox = archive_detection_bbox(record)
            if bbox is None:
                skipped["missing_archive_bbox"] += 1
                continue
            yolo_box = bbox_xyxy_to_yolo(bbox, width, height)
            if yolo_box is None:
                skipped["invalid_archive_bbox"] += 1
                continue
            category = archive_category_for_export(record, label_mode)
            if category is None or category not in class_ids:
                skipped["unknown_archive_category"] += 1
                continue
            class_id = class_ids[category]
            x_center, y_center, box_width, box_height = yolo_box
            label_lines.append(
                f"{class_id} {x_center:.6f} {y_center:.6f} {box_width:.6f} {box_height:.6f}"
            )
            split_label_counts[split] += 1
            has_exportable_record = True

        if not has_exportable_record:
            skipped["images_without_exportable_archive_records"] += 1
            continue

        link_or_copy_image(image_path, destination_image, image_mode)
        if label_lines:
            destination_label.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
            positive_image_counts[split] += 1
        elif has_negative_only_record:
            destination_label.write_text("", encoding="utf-8")
            negative_image_counts[split] += 1
        else:
            skipped["archive_images_without_labels_or_negatives"] += 1
            if destination_image.exists() or destination_image.is_symlink():
                destination_image.unlink()
            continue
        split_image_counts[split] += 1

    dataset_yaml = {
        "path": str(output_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "names": {index: name for index, name in enumerate(categories)},
    }
    (output_dir / "dataset.yaml").write_text(yaml.safe_dump(dataset_yaml, sort_keys=False), encoding="utf-8")
    (output_dir / "archive_export_snapshot.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = {
        "source": "archive_export",
        "archive_export_source": source_label,
        "output_dir": str(output_dir),
        "label_mode": label_mode,
        "image_mode": image_mode,
        "val_ratio": val_ratio,
        "categories": categories,
        "cache_dir": str(cache_dir),
        "archive_detection_count": len(detections),
        "review_state_counts": dict(review_state_counts),
        "split_image_counts": dict(split_image_counts),
        "split_label_counts": dict(split_label_counts),
        "positive_image_counts": dict(positive_image_counts),
        "negative_image_counts": dict(negative_image_counts),
        "skipped_records": dict(skipped),
    }
    (output_dir / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export either the unified sign manifest or a reviewed Signomat archive export to a YOLO detection dataset."
    )
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "data/training/prepared/unified_sign_manifest.jsonl",
        help="Path to the normalized manifest JSONL. Ignored when archive export mode is used.",
    )
    parser.add_argument(
        "--archive-export",
        type=Path,
        default=None,
        help="Path to an archive training export JSON created from the site.",
    )
    parser.add_argument(
        "--archive-export-url",
        default=None,
        help="HTTP URL for an archive training export JSON created from the site.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
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
    parser.add_argument(
        "--label-mode",
        choices=("any_sign", "broad"),
        default="any_sign",
        help="Whether to export a one-class detector dataset or the legacy broad-family dataset.",
    )
    parser.add_argument(
        "--download-timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout used when downloading archive export JSON or archive images.",
    )
    parser.add_argument(
        "--archive-cache-dir",
        type=Path,
        default=None,
        help="Optional cache directory for downloaded archive images. Defaults inside the output directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    categories = load_plan_categories(args.plan, args.label_mode)
    archive_mode = args.archive_export is not None or args.archive_export_url is not None

    output_dir = args.output_dir
    if output_dir is None:
        if archive_mode:
            export_name = "yolo_archive_any_signs" if args.label_mode == "any_sign" else "yolo_archive_broad_signs"
        else:
            export_name = "yolo_any_signs" if args.label_mode == "any_sign" else "yolo_broad_signs"
        output_dir = repo_root / "data/training/exports" / export_name

    if archive_mode:
        payload, source_label = load_archive_export(
            archive_export=args.archive_export,
            archive_export_url=args.archive_export_url,
            timeout_seconds=args.download_timeout_seconds,
        )
        cache_dir = args.archive_cache_dir or (output_dir / "_archive_cache")
        summary = export_archive_to_yolo(
            payload=payload,
            source_label=source_label,
            output_dir=output_dir,
            categories=categories,
            label_mode=args.label_mode,
            val_ratio=args.val_ratio,
            image_mode=args.image_mode,
            cache_dir=cache_dir,
            timeout_seconds=args.download_timeout_seconds,
        )
    else:
        summary = export_manifest_to_yolo(
            manifest_path=args.manifest,
            output_dir=output_dir,
            repo_root=repo_root,
            categories=categories,
            label_mode=args.label_mode,
            val_ratio=args.val_ratio,
            image_mode=args.image_mode,
        )

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
