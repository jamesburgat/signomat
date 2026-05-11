from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import cv2
import yaml


DEFAULT_TAXONOMY_PATH = "training/classifier_taxonomy_us.yaml"
DEFAULT_OUTPUT_DIR = "data/training/exports/classifier_us_signs"
DEFAULT_ARCHIVE_OUTPUT_DIR = "data/training/exports/classifier_archive_signs"

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

    request = urllib.request.Request(source, headers={"User-Agent": "signomat-archive-classifier-export/0.1"})
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


def archive_label_for_export(record: dict[str, Any], label_source: str) -> str | None:
    specific = str(record.get("specificLabel") or "").strip()
    category = str(record.get("categoryLabel") or "").strip()
    if label_source == "specific":
        return specific or None
    if label_source == "category":
        return category or None
    return specific or category or None


def archive_frame_source(record: dict[str, Any]) -> str | None:
    for key in ("cleanFrameUrl", "annotatedFrameUrl"):
        value = record.get(key)
        if value:
            return str(value)
    return None


def slugify_label(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown_sign"


def archive_class_id(label: str, label_map: dict[str, str], class_map: dict[str, str]) -> str:
    existing = label_map.get(label)
    if existing:
        return existing

    base = slugify_label(label)
    candidate = base
    if candidate in class_map and class_map[candidate] != label:
        suffix = hashlib.sha1(label.encode("utf-8")).hexdigest()[:6]
        candidate = f"{base}_{suffix}"
    label_map[label] = candidate
    class_map[candidate] = label
    return candidate


def archive_crop_filename(record: dict[str, Any], class_id: str, source_path: Path) -> str:
    digest_source = json.dumps(
        {
            "event_id": record.get("eventId"),
            "class_id": class_id,
            "source": str(source_path),
            "specificLabel": record.get("specificLabel"),
            "categoryLabel": record.get("categoryLabel"),
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    stem = str(record.get("eventId") or source_path.stem or "archive_crop")
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)
    return f"{safe_stem}_{digest}.jpg"


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


def export_archive_classifier_dataset(
    payload: dict[str, Any],
    source_label: str,
    output_dir: Path,
    val_ratio: float,
    pad_ratio: float,
    min_crop_size: int,
    image_quality: int,
    summary_only: bool,
    cache_dir: Path,
    timeout_seconds: float,
    label_source: str,
) -> dict[str, Any]:
    detections = payload.get("detections") or []
    if not isinstance(detections, list):
        raise SystemExit("Archive export JSON must contain a top-level detections list.")

    class_label_map: dict[str, str] = {}
    class_id_map: dict[str, str] = {}
    candidate_records: list[dict[str, Any]] = []
    skipped = Counter()
    review_state_counts = Counter()

    for record in detections:
        if not isinstance(record, dict):
            skipped["non_object_detection_records"] += 1
            continue
        review_state = str(record.get("reviewState") or "unreviewed")
        review_state_counts[review_state] += 1
        if review_state != "reviewed":
            skipped[f"review_state_{review_state}"] += 1
            continue

        label = archive_label_for_export(record, label_source)
        if not label:
            skipped["missing_archive_label"] += 1
            continue

        sign_crop_source = record.get("signCropUrl")
        frame_source = archive_frame_source(record)
        bbox = archive_detection_bbox(record)

        if sign_crop_source:
            source = str(sign_crop_source)
            uses_sign_crop = True
        elif frame_source and bbox is not None:
            source = frame_source
            uses_sign_crop = False
        else:
            skipped["missing_archive_image_or_bbox"] += 1
            continue

        class_id = archive_class_id(label, class_label_map, class_id_map)
        split_seed = str(record.get("eventId") or source)
        candidate_records.append(
            {
                "record": record,
                "label": label,
                "class_id": class_id,
                "source": source,
                "uses_sign_crop": uses_sign_crop,
                "bbox_xyxy": bbox,
                "split": split_name_for_path(split_seed, val_ratio),
            }
        )

    active_class_ids = sorted(class_id_map)
    summary: dict[str, Any] = {
        "source": "archive_export",
        "archive_export_source": source_label,
        "output_dir": str(output_dir),
        "summary_only": summary_only,
        "val_ratio": val_ratio,
        "pad_ratio": pad_ratio,
        "min_crop_size": min_crop_size,
        "archive_label_source": label_source,
        "review_state_counts": dict(review_state_counts),
        "candidate_record_count": len(candidate_records),
        "class_ids": active_class_ids,
        "class_label_map": dict(sorted(class_id_map.items())),
        "skipped_records": dict(skipped),
    }

    if summary_only:
        return summary

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val"):
        for class_id in active_class_ids:
            (output_dir / split / class_id).mkdir(parents=True, exist_ok=True)

    crop_manifest_entries: list[str] = []
    exported_class_counts = Counter()
    exported_split_counts = Counter()
    export_skipped = Counter(summary["skipped_records"])

    for item in candidate_records:
        source = str(item["source"])
        try:
            image_path = cache_archive_image(source, cache_dir=cache_dir, timeout_seconds=timeout_seconds)
        except Exception:
            export_skipped["failed_archive_image_download"] += 1
            continue

        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            export_skipped["unreadable_image"] += 1
            continue

        if item["uses_sign_crop"]:
            crop = image
            crop_xyxy = None
            crop_height, crop_width = crop.shape[:2]
            if crop_width < min_crop_size or crop_height < min_crop_size:
                export_skipped["too_small_crop"] += 1
                continue
        else:
            height, width = image.shape[:2]
            bounds = clamp_crop_bounds(item["bbox_xyxy"], width, height, pad_ratio)
            if bounds is None:
                export_skipped["invalid_bbox"] += 1
                continue
            left, top, right, bottom = bounds
            if (right - left) < min_crop_size or (bottom - top) < min_crop_size:
                export_skipped["too_small_crop"] += 1
                continue
            crop = image[top:bottom, left:right]
            crop_xyxy = [left, top, right, bottom]

        if crop.size == 0:
            export_skipped["empty_crop"] += 1
            continue

        record = dict(item["record"])
        class_id = str(item["class_id"])
        split = str(item["split"])
        crop_path = output_dir / split / class_id / archive_crop_filename(record, class_id, image_path)
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
                    "archive_label": item["label"],
                    "event_id": record.get("eventId"),
                    "trip_id": record.get("tripId"),
                    "review_state": record.get("reviewState"),
                    "used_sign_crop_asset": item["uses_sign_crop"],
                    "source_image": source,
                    "bbox_xyxy": item["bbox_xyxy"],
                    "crop_xyxy": crop_xyxy,
                }
            )
        )

    crop_manifest_path = output_dir / "crop_manifest.jsonl"
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
    (output_dir / "archive_export_snapshot.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_dir / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export cropped sign images for classifier training from either the unified manifest or an archive training export.")
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "data/training/prepared/unified_sign_manifest.jsonl",
        help="Path to the normalized manifest JSONL.",
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
        "--taxonomy",
        type=Path,
        default=repo_root / DEFAULT_TAXONOMY_PATH,
        help="YAML taxonomy defining classifier classes and raw-label matches.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
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
    parser.add_argument(
        "--archive-label-source",
        choices=("specific", "category", "specific_or_category"),
        default="specific_or_category",
        help="Which reviewed archive label field should become the classifier class name.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    archive_mode = args.archive_export is not None or args.archive_export_url is not None
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = repo_root / (DEFAULT_ARCHIVE_OUTPUT_DIR if archive_mode else DEFAULT_OUTPUT_DIR)

    if archive_mode:
        payload, source_label = load_archive_export(
            archive_export=args.archive_export,
            archive_export_url=args.archive_export_url,
            timeout_seconds=args.download_timeout_seconds,
        )
        cache_dir = args.archive_cache_dir or (output_dir / "_archive_cache")
        summary = export_archive_classifier_dataset(
            payload=payload,
            source_label=source_label,
            output_dir=output_dir,
            val_ratio=args.val_ratio,
            pad_ratio=args.pad_ratio,
            min_crop_size=args.min_crop_size,
            image_quality=args.image_quality,
            summary_only=args.summary_only,
            cache_dir=cache_dir,
            timeout_seconds=args.download_timeout_seconds,
            label_source=args.archive_label_source,
        )
    else:
        summary = export_classifier_dataset(
            manifest_path=args.manifest,
            taxonomy_path=args.taxonomy,
            output_dir=output_dir,
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
