from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DETECTOR_THRESHOLD = 0.6
DEFAULT_CLASSIFIER_THRESHOLD = 0.75


def resolve_output_dir(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path.cwd() / path


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def clean_label(value: str | None) -> str:
    if not value:
        return "unknown"
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def link_or_copy(source: Path, destination: Path, mode: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    if mode == "copy":
        shutil.copy2(source, destination)
        return "copy"
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def fetch_review_rows(
    connection: sqlite3.Connection,
    trip_ids: list[str],
    detector_threshold: float,
    classifier_threshold: float,
    treat_unknown_signs_as_false_positives: bool,
) -> list[sqlite3.Row]:
    trip_filter = ""
    params: list[Any] = [detector_threshold, classifier_threshold]
    if trip_ids:
        placeholders = ",".join("?" for _ in trip_ids)
        trip_filter = f"AND trip_id IN ({placeholders})"
        params.extend(trip_ids)
    unknown_clause = "OR raw_classifier_label = 'unknown_sign'" if treat_unknown_signs_as_false_positives else ""
    sql = f"""
        SELECT *
        FROM detections
        WHERE (
            detector_confidence < ?
            OR (raw_classifier_label != 'unknown_sign' AND classifier_confidence < ?)
            {unknown_clause}
        )
        {trip_filter}
        ORDER BY trip_id, timestamp_utc, event_id
    """
    return list(connection.execute(sql, params))


def export_review(
    db_path: Path,
    base_data_dir: Path,
    output_dir: Path,
    detector_threshold: float,
    classifier_threshold: float,
    treat_unknown_signs_as_false_positives: bool,
    trip_ids: list[str],
    asset_mode: str,
    include_crops: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    rows = fetch_review_rows(
        connection,
        trip_ids=trip_ids,
        detector_threshold=detector_threshold,
        classifier_threshold=classifier_threshold,
        treat_unknown_signs_as_false_positives=treat_unknown_signs_as_false_positives,
    )

    manifest_path = output_dir / "manifest.csv"
    missing_assets: list[dict[str, str]] = []
    copied = {"annotated": 0, "crop": 0}
    link_modes: dict[str, int] = {}

    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "trip_id",
            "event_id",
            "timestamp_utc",
            "category_label",
            "specific_label",
            "raw_classifier_label",
            "detector_confidence",
            "classifier_confidence",
            "gps_lat",
            "gps_lon",
            "review_reason",
            "annotated_review_path",
            "crop_review_path",
            "source_annotated_frame_path",
            "source_crop_path",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            event_id = row["event_id"]
            trip_id = row["trip_id"]
            label = clean_label(row["category_label"])
            stem = f"{trip_id}__{row['timestamp_utc'].replace(':', '-') if row['timestamp_utc'] else 'no_time'}__{label}__{event_id}"
            reasons: list[str] = []
            if row["detector_confidence"] is None or row["detector_confidence"] < detector_threshold:
                reasons.append("low_detector_confidence")
            if row["raw_classifier_label"] == "unknown_sign" and treat_unknown_signs_as_false_positives:
                reasons.append("unknown_sign")
            elif row["classifier_confidence"] is None or row["classifier_confidence"] < classifier_threshold:
                reasons.append("low_classifier_confidence")

            annotated_review_path = ""
            crop_review_path = ""
            asset_specs = [("annotated_frame_path", "annotated", "annotated.jpg")]
            if include_crops:
                asset_specs.append(("sign_crop_path", "crops", "crop.jpg"))
            for source_key, subdir, suffix in asset_specs:
                source_value = row[source_key]
                if not source_value:
                    continue
                source_path = base_data_dir / source_value
                if not source_path.exists():
                    missing_assets.append({"event_id": event_id, "path": str(source_path)})
                    continue
                destination = output_dir / subdir / trip_id / f"{stem}__{suffix}"
                mode_used = link_or_copy(source_path, destination, asset_mode)
                link_modes[mode_used] = link_modes.get(mode_used, 0) + 1
                if subdir == "annotated":
                    annotated_review_path = str(destination)
                    copied["annotated"] += 1
                else:
                    crop_review_path = str(destination)
                    copied["crop"] += 1

            writer.writerow(
                {
                    "trip_id": trip_id,
                    "event_id": event_id,
                    "timestamp_utc": row["timestamp_utc"],
                    "category_label": row["category_label"],
                    "specific_label": row["specific_label"],
                    "raw_classifier_label": row["raw_classifier_label"],
                    "detector_confidence": row["detector_confidence"],
                    "classifier_confidence": row["classifier_confidence"],
                    "gps_lat": row["gps_lat"],
                    "gps_lon": row["gps_lon"],
                    "review_reason": ";".join(reasons),
                    "annotated_review_path": annotated_review_path,
                    "crop_review_path": crop_review_path,
                    "source_annotated_frame_path": row["annotated_frame_path"],
                    "source_crop_path": row["sign_crop_path"],
                }
            )

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "db_path": str(db_path),
        "base_data_dir": str(base_data_dir),
        "output_dir": str(output_dir),
        "detector_threshold": detector_threshold,
        "classifier_threshold": classifier_threshold,
        "treat_unknown_signs_as_false_positives": treat_unknown_signs_as_false_positives,
        "include_crops": include_crops,
        "trip_ids": trip_ids,
        "review_count": len(rows),
        "asset_counts": copied,
        "link_modes": link_modes,
        "missing_assets": missing_assets,
        "manifest_path": str(manifest_path),
        "sync_note": "This folder is outside the Signomat base data directory and is not enqueued for Cloudflare sync.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export low-confidence Signomat detections for manual false-positive review.")
    parser.add_argument("--db", type=Path, default=Path.home() / "signomat-data/db/signomat.db")
    parser.add_argument("--base-data-dir", type=Path, default=Path.home() / "signomat-data")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "Desktop/signomat_false_positives",
        help="Review folder. Defaults outside the Signomat sync data root.",
    )
    parser.add_argument("--detector-threshold", type=float, default=DEFAULT_DETECTOR_THRESHOLD)
    parser.add_argument("--classifier-threshold", type=float, default=DEFAULT_CLASSIFIER_THRESHOLD)
    parser.add_argument(
        "--treat-unknown-signs-as-false-positives",
        action="store_true",
        help="Export unknown_sign rows solely because they are unknown. By default unknown signs are kept if they clear the detector threshold.",
    )
    parser.add_argument("--trip-id", action="append", default=[], help="Trip ID to export. Repeat for multiple trips.")
    parser.add_argument("--asset-mode", choices=("hardlink", "copy"), default="hardlink")
    parser.add_argument(
        "--include-crops",
        action="store_true",
        help="Also export sign crop images when they exist. By default only annotated frames are exported.",
    )
    parser.add_argument(
        "--allow-output-inside-base-data-dir",
        action="store_true",
        help="Allow writing inside the Signomat base data directory. This is disabled by default to avoid sync uploads.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = resolve_output_dir(args.output_dir)
    if is_relative_to(output_dir, args.base_data_dir) and not args.allow_output_inside_base_data_dir:
        raise SystemExit(
            f"Refusing to write review export inside sync base data dir: {output_dir}. "
            "Choose an output outside the base data dir."
        )
    summary = export_review(
        db_path=args.db,
        base_data_dir=args.base_data_dir,
        output_dir=output_dir,
        detector_threshold=args.detector_threshold,
        classifier_threshold=args.classifier_threshold,
        treat_unknown_signs_as_false_positives=args.treat_unknown_signs_as_false_positives,
        trip_ids=args.trip_id,
        asset_mode=args.asset_mode,
        include_crops=args.include_crops,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
