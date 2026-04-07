from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import yaml


BROAD_CATEGORIES = (
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


def load_plan(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def slugify_label(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def map_to_broad_category(raw_label: str) -> str:
    label = slugify_label(raw_label)
    if not label:
        return "unknown_sign"
    if "stop" in label:
        return "stop"
    if "yield" in label:
        return "yield"
    if "speed" in label or "mph" in label:
        return "speed_limit"
    if "cross" in label or "pedestrian" in label or "school" in label:
        return "crossing"
    if "work" in label or "construction" in label or "orange" in label:
        return "work_zone_general"
    if "guide" in label or "highway" in label or "freeway" in label or "motorway" in label or "green" in label:
        return "guide_general"
    if "service" in label or "blue" in label or "hospital" in label or "gas" in label or "food" in label or "lodging" in label:
        return "service_general"
    if "warning" in label or "diamond" in label or "curve" in label or "merge" in label:
        return "warning_general"
    if "regulatory" in label or "prohib" in label or "mandatory" in label or "limit" in label or "turn" in label:
        return "regulatory_general"
    if "text" in label or "street_name" in label or "word" in label or "rect" in label or "white" in label:
        return "text_rectangular_general"
    if "sign" in label:
        return "other_sign_like"
    return "unknown_sign"


def relpath_or_str(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def coco_bbox_to_xyxy(bbox: list[Any]) -> list[float] | None:
    if len(bbox) != 4:
        return None
    x, y, w, h = [float(value) for value in bbox]
    return [x, y, x + w, y + h]


def _file_name_from_image(image: dict[str, Any]) -> str | None:
    return image.get("file_name") or image.get("path") or image.get("name")


def parse_coco_annotation_file(annotation_path: Path, dataset_id: str, image_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    if not all(key in payload for key in ("images", "annotations", "categories")):
        return []
    categories = {item["id"]: item.get("name", str(item["id"])) for item in payload.get("categories", [])}
    images = {item["id"]: item for item in payload.get("images", [])}
    records: list[dict[str, Any]] = []
    for annotation in payload.get("annotations", []):
        bbox = annotation.get("bbox")
        if bbox is None:
            continue
        image = images.get(annotation.get("image_id"))
        if image is None:
            continue
        file_name = _file_name_from_image(image)
        if not file_name:
            continue
        image_path = image_root / file_name
        raw_label = categories.get(annotation.get("category_id"), "unknown_sign")
        records.append(
            {
                "dataset_id": dataset_id,
                "source_annotation": relpath_or_str(annotation_path, repo_root),
                "image_path": relpath_or_str(image_path, repo_root),
                "raw_label": raw_label,
                "broad_category": map_to_broad_category(raw_label),
                "bbox_xyxy": coco_bbox_to_xyxy(bbox),
            }
        )
    return records


def csv_label_column(fieldnames: list[str]) -> str | None:
    for candidate in ("label", "class", "category", "Annotation tag", "annotation_tag"):
        if candidate in fieldnames:
            return candidate
    return None


def csv_filename_column(fieldnames: list[str]) -> str | None:
    for candidate in ("filename", "file_name", "image", "image_path"):
        if candidate in fieldnames:
            return candidate
    return None


def parse_lisa_csv_annotation_file(annotation_path: Path, dataset_id: str, image_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    with annotation_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        label_column = csv_label_column(reader.fieldnames)
        filename_column = csv_filename_column(reader.fieldnames)
        if label_column is None or filename_column is None:
            return []
        records: list[dict[str, Any]] = []
        for row in reader:
            file_name = row.get(filename_column)
            raw_label = row.get(label_column)
            if not file_name or not raw_label:
                continue
            x1 = row.get("Upper left corner X") or row.get("x1") or row.get("xmin")
            y1 = row.get("Upper left corner Y") or row.get("y1") or row.get("ymin")
            x2 = row.get("Lower right corner X") or row.get("x2") or row.get("xmax")
            y2 = row.get("Lower right corner Y") or row.get("y2") or row.get("ymax")
            bbox = None
            if all(value not in {None, ""} for value in (x1, y1, x2, y2)):
                bbox = [float(x1), float(y1), float(x2), float(y2)]
            records.append(
                {
                    "dataset_id": dataset_id,
                    "source_annotation": relpath_or_str(annotation_path, repo_root),
                    "image_path": relpath_or_str(image_root / file_name, repo_root),
                    "raw_label": raw_label,
                    "broad_category": map_to_broad_category(raw_label),
                    "bbox_xyxy": bbox,
                }
            )
        return records


def parse_pascal_voc_annotation_file(annotation_path: Path, dataset_id: str, image_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    root = ET.fromstring(annotation_path.read_text(encoding="utf-8"))
    filename_node = root.find("filename")
    if filename_node is None or not filename_node.text:
        return []
    file_name = filename_node.text.strip()
    records: list[dict[str, Any]] = []
    for obj in root.findall("object"):
        name_node = obj.find("name")
        box_node = obj.find("bndbox")
        if name_node is None or not name_node.text or box_node is None:
            continue
        xmin = box_node.findtext("xmin")
        ymin = box_node.findtext("ymin")
        xmax = box_node.findtext("xmax")
        ymax = box_node.findtext("ymax")
        bbox = None
        if all(value is not None for value in (xmin, ymin, xmax, ymax)):
            bbox = [float(xmin), float(ymin), float(xmax), float(ymax)]
        raw_label = name_node.text.strip()
        records.append(
            {
                "dataset_id": dataset_id,
                "source_annotation": relpath_or_str(annotation_path, repo_root),
                "image_path": relpath_or_str(image_root / file_name, repo_root),
                "raw_label": raw_label,
                "broad_category": map_to_broad_category(raw_label),
                "bbox_xyxy": bbox,
            }
        )
    return records


def detect_annotation_parser(annotation_path: Path) -> str | None:
    suffix = annotation_path.suffix.lower()
    if suffix == ".xml":
        return "voc_xml"
    if suffix == ".csv":
        return "lisa_csv"
    if suffix == ".json":
        return "coco_json"
    return None


def normalize_dataset(repo_root: Path, dataset: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dataset_root = repo_root / dataset["local_root"]
    image_root = dataset_root / dataset.get("expected", {}).get("images_dir", "images")
    annotation_root = dataset_root / dataset.get("expected", {}).get("annotations_dir", "annotations")
    records: list[dict[str, Any]] = []
    parser_counts: Counter[str] = Counter()

    if annotation_root.exists():
        for annotation_path in sorted(annotation_root.rglob("*")):
            if not annotation_path.is_file():
                continue
            parser = detect_annotation_parser(annotation_path)
            if parser is None:
                continue
            if parser == "voc_xml":
                parsed = parse_pascal_voc_annotation_file(annotation_path, dataset["id"], image_root, repo_root)
            elif parser == "lisa_csv":
                parsed = parse_lisa_csv_annotation_file(annotation_path, dataset["id"], image_root, repo_root)
            else:
                parsed = parse_coco_annotation_file(annotation_path, dataset["id"], image_root, repo_root)
            if parsed:
                parser_counts[parser] += 1
                records.extend(parsed)

    category_counts = Counter(record["broad_category"] for record in records)
    summary = {
        "id": dataset["id"],
        "name": dataset["name"],
        "local_root": str(dataset_root),
        "annotation_root": str(annotation_root),
        "record_count": len(records),
        "parser_counts": dict(parser_counts),
        "broad_category_counts": dict(sorted(category_counts.items())),
    }
    return records, summary


def normalize_all(plan: dict[str, Any], repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for dataset in plan.get("datasets", []):
        records, summary = normalize_dataset(repo_root, dataset)
        all_records.extend(records)
        summaries.append(summary)
    overall_counts = Counter(record["broad_category"] for record in all_records)
    return all_records, {
        "version": plan.get("version", 1),
        "strategy": plan["targets"]["strategy"],
        "datasets": summaries,
        "overall_broad_category_counts": dict(sorted(overall_counts.items())),
        "total_records": len(all_records),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="training/datasets.yaml")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    plan = load_plan(repo_root / args.config)
    records, summary = normalize_all(plan, repo_root)

    prepared_dir = repo_root / plan["workspace"]["root"] / "prepared"
    manifest_path = prepared_dir / "unified_sign_manifest.jsonl"
    summary_path = prepared_dir / "normalization_summary.json"
    write_jsonl(manifest_path, records)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "summary": str(summary_path), "records": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
