from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


DEFAULT_OUTPUT_PATH = "training/classifier_taxonomy_dataset.yaml"
DEFAULT_EXCLUDED_LABELS = ("other-sign",)


def class_id_for_raw_label(raw_label: str, used_ids: set[str]) -> str:
    class_id = re.sub(r"[^a-z0-9]+", "_", raw_label.lower()).strip("_")
    if not class_id:
        class_id = "sign"
    candidate = class_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{class_id}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def load_label_counts(manifest_path: Path) -> tuple[Counter[str], dict[str, Counter[str]]]:
    label_counts: Counter[str] = Counter()
    dataset_counts: dict[str, Counter[str]] = defaultdict(Counter)
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record: dict[str, Any] = json.loads(line)
            raw_label = str(record.get("raw_label") or "")
            dataset_id = str(record.get("dataset_id") or "unknown")
            label_counts[raw_label] += 1
            dataset_counts[raw_label][dataset_id] += 1
    return label_counts, dataset_counts


def build_taxonomy(
    manifest_path: Path,
    min_count: int,
    excluded_labels: set[str],
) -> dict[str, Any]:
    label_counts, dataset_counts = load_label_counts(manifest_path)
    selected_labels = [
        label
        for label, count in sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= min_count and label not in excluded_labels
    ]

    used_ids: set[str] = set()
    classes: list[dict[str, Any]] = []
    for raw_label in selected_labels:
        classes.append(
            {
                "id": class_id_for_raw_label(raw_label, used_ids),
                "exact_raw_labels": [raw_label],
                "sample_count": label_counts[raw_label],
                "dataset_counts": dict(sorted(dataset_counts[raw_label].items())),
            }
        )

    return {
        "version": 1,
        "name": f"dataset_raw_label_classifier_min{min_count}_v1",
        "description": (
            "Data-driven crop-classifier taxonomy generated from the normalized "
            "manifest. Each class maps to one raw dataset label so the classifier "
            "learns specific sign labels instead of the broad detector families."
        ),
        "source_manifest": str(manifest_path),
        "min_class_count": min_count,
        "excluded_raw_labels": sorted(excluded_labels),
        "classes": classes,
    }


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate a classifier taxonomy from manifest raw-label counts.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "data/training/prepared/unified_sign_manifest.jsonl",
        help="Normalized manifest JSONL to count raw labels from.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / DEFAULT_OUTPUT_PATH,
        help="Taxonomy YAML output path.",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=100,
        help="Minimum raw-label sample count to include as a classifier class.",
    )
    parser.add_argument(
        "--exclude-raw-label",
        action="append",
        default=list(DEFAULT_EXCLUDED_LABELS),
        help="Raw label to exclude. Can be passed multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    taxonomy = build_taxonomy(
        manifest_path=args.manifest,
        min_count=args.min_count,
        excluded_labels=set(args.exclude_raw_label),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(taxonomy, sort_keys=False, width=120), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "taxonomy_name": taxonomy["name"],
                "class_count": len(taxonomy["classes"]),
                "mapped_record_count": sum(item["sample_count"] for item in taxonomy["classes"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
