# Training Data Plan

Signomat currently runs a heuristic detector and classifier on the Pi. This
document defines the first training-data stack for replacing that with a
broader, recall-heavy model.

## Selected Datasets

- `Mapillary Traffic Sign Dataset`
  - Role: primary broad-coverage dataset
  - Why: best first source for diverse sign appearances and large sign-class coverage
  - Source: https://www.mapillary.com/dataset/trafficsign

- `LISA Traffic Sign Dataset`
  - Role: US-focused supplement
  - Why: improves coverage for US sign conventions that matter more for Signomat than European-only datasets
  - Source: https://cvrr.ucsd.edu/LISA/lisa-traffic-sign-dataset.html

- `GLARE`
  - Role: robustness supplement
  - Why: adds hard examples under strong glare and windshield-style reflections
  - Source: https://arxiv.org/abs/2209.08716

## Recommended Label Strategy

Use broad-first categories for detector training and archive ingest:

- `stop`
- `yield`
- `speed_limit`
- `regulatory_general`
- `warning_general`
- `crossing`
- `work_zone_general`
- `guide_general`
- `service_general`
- `text_rectangular_general`
- `other_sign_like`
- `unknown_sign`

This keeps recall high and lets review or later classifiers sort into more
specific sign families after capture.

## Immediate Runtime Changes

The Pi runtime has been loosened to better match that strategy:

- `save_unknown_signs: true`
- lower detector/classifier thresholds
- new sign-like color proposals for `green`, `white`, and `orange`
- new broad raw labels for:
  - `guide_sign`
  - `regulatory_rect`
  - `service_sign`
  - `work_zone_sign`

This is still heuristic, but it is now much closer to “detect first, sort
later.”

## Workspace Setup

Run:

```bash
. .venv/bin/activate
python scripts/prepare_sign_training_workspace.py
python scripts/normalize_sign_datasets.py
python scripts/export_yolo_detection_dataset.py
```

That will:

- create `data/training/`
- inventory which raw dataset folders already exist
- write `data/training/manifest/dataset_inventory.json`
- write `data/training/manifest/label_schema.json`
- normalize supported raw annotations into `data/training/prepared/unified_sign_manifest.jsonl`
- write `data/training/prepared/normalization_summary.json`
- export a trainer-ready YOLO dataset under `data/training/exports/yolo_broad_signs`

Expected raw dataset roots:

- `data/training/raw/mapillary`
- `data/training/raw/lisa`
- `data/training/raw/glare`

Supported annotation inputs today:

- COCO-style `.json`
- CSV files in a LISA-like box format
- Pascal VOC `.xml`

## Next Model Step

The next practical milestone is:

1. normalize Mapillary, LISA, and GLARE into one broad-category manifest
2. train a high-recall detector on those broad categories
3. export an edge-friendly model for the Pi
4. keep the taxonomy layer on top so archive grouping can still evolve
