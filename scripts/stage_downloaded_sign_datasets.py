from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def natural_sort_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def slugify(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
    return slug or "item"


def clear_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def reset_dir(path: Path, replace: bool) -> None:
    if path.exists() or path.is_symlink():
        if not replace and any(path.iterdir()):
            raise RuntimeError(f"Destination is not empty: {path}. Re-run with --replace to rebuild it.")
        clear_path(path)
    path.mkdir(parents=True, exist_ok=True)


def iter_image_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            yield path


def link_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() and destination.resolve() == source.resolve():
            return
        raise RuntimeError(f"Refusing to overwrite existing path: {destination}")
    destination.symlink_to(source)


def discover_dirs(root: Path, pattern: str) -> list[Path]:
    return sorted((path for path in root.rglob(pattern) if path.is_dir()), key=lambda path: path.as_posix())


def stage_mapillary(
    fb_links_root: Path,
    dataset_root: Path,
    include_partial: bool,
    replace: bool,
) -> dict[str, Any]:
    images_dest = dataset_root / "images"
    annotations_dest = dataset_root / "annotations"
    reset_dir(images_dest, replace=replace)
    reset_dir(annotations_dest, replace=replace)

    image_dirs = sorted((path for path in fb_links_root.glob("images*") if path.is_dir()), key=lambda path: natural_sort_key(path.name))
    if not image_dirs:
        raise RuntimeError(f"No fb_links image folders found under {fb_links_root}")

    image_count = 0
    for image_dir in image_dirs:
        for image_path in iter_image_files(image_dir):
            link_file(image_path, images_dest / image_path.name)
            image_count += 1

    annotation_sets: list[tuple[str, list[Path]]] = [
        ("fully", discover_dirs(fb_links_root, "mtsd_v2_fully_annotated/annotations")),
    ]
    if include_partial:
        annotation_sets.append(("partial", discover_dirs(fb_links_root, "mtsd_v2_partially_annotated/annotations")))

    annotation_count = 0
    annotation_sources: dict[str, int] = {}
    for label, sources in annotation_sets:
        if not sources:
            continue
        for source_dir in sources:
            for annotation_path in sorted(source_dir.glob("*.json")):
                link_file(annotation_path, annotations_dest / label / annotation_path.name)
                annotation_count += 1
        annotation_sources[label] = sum(1 for _ in (annotations_dest / label).glob("*.json"))

    return {
        "dataset": "mapillary",
        "image_dirs": [str(path) for path in image_dirs],
        "image_count": image_count,
        "annotation_sources": annotation_sources,
        "annotation_count": annotation_count,
        "included_partial_annotations": include_partial,
    }


def stage_glare(glare_sources: list[Path], dataset_root: Path, replace: bool) -> dict[str, Any]:
    images_dest = dataset_root / "images"
    annotations_dest = dataset_root / "annotations"
    reset_dir(images_dest, replace=replace)
    reset_dir(annotations_dest, replace=replace)

    valid_sources: list[Path] = []
    image_count = 0
    annotation_count = 0

    for source_root in glare_sources:
        images_root = source_root / "Images"
        if not images_root.exists():
            continue
        frame_csvs = sorted(images_root.rglob("frameAnnotations.csv"))
        if not frame_csvs:
            continue
        valid_sources.append(source_root)
        root_alias = slugify(source_root.name)

        for image_path in iter_image_files(images_root):
            link_file(image_path, images_dest / image_path.name)
            image_count += 1

        for csv_path in frame_csvs:
            rel_parent = csv_path.parent.relative_to(images_root)
            dest_name = f"{root_alias}__{slugify(str(rel_parent))}.csv"
            link_file(csv_path, annotations_dest / dest_name)
            annotation_count += 1

    if not valid_sources:
        raise RuntimeError("No annotated GLARE sources were found.")

    return {
        "dataset": "glare",
        "sources": [str(path) for path in valid_sources],
        "image_count": image_count,
        "annotation_count": annotation_count,
    }


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    downloads_root = Path.home() / "Downloads"
    parser = argparse.ArgumentParser(description="Stage downloaded sign datasets into the Signomat raw workspace.")
    parser.add_argument("--downloads-root", type=Path, default=downloads_root)
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--fb-links-root", type=Path, default=downloads_root / "fb_links")
    parser.add_argument(
        "--glare-source",
        action="append",
        dest="glare_sources",
        default=[
            str(downloads_root / "GLARE"),
            str(downloads_root / "GLARE 2"),
            str(downloads_root / "GLARE 4"),
        ],
        help="Path to a GLARE source root. Can be specified multiple times.",
    )
    parser.add_argument(
        "--include-mapillary-partial",
        action="store_true",
        help="Also stage the partially annotated MTSD set. Off by default because it is not exhaustively labeled.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing staged mapillary/glare data under data/training/raw.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    raw_root = repo_root / "data" / "training" / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    glare_sources = [Path(item).expanduser().resolve() for item in args.glare_sources]
    summary = {
        "mapillary": stage_mapillary(
            fb_links_root=args.fb_links_root.expanduser().resolve(),
            dataset_root=raw_root / "mapillary",
            include_partial=args.include_mapillary_partial,
            replace=args.replace,
        ),
        "glare": stage_glare(
            glare_sources=glare_sources,
            dataset_root=raw_root / "glare",
            replace=args.replace,
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
