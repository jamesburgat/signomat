# Training Data Plan

Signomat currently runs a heuristic detector and classifier on the Pi. This
document defines the first training-data stack for replacing that with a
broader, recall-heavy model.

## Selected Datasets

- `Mapillary Traffic Sign Dataset`
  - Role: primary broad-coverage dataset
  - Why: best first source for diverse sign appearances and large sign-class coverage
  - Source: https://www.mapillary.com/dataset/trafficsign

- `GLARE`
  - Role: robustness supplement
  - Why: adds hard examples under strong glare and windshield-style reflections
  - Source: https://arxiv.org/abs/2209.08716

## Recommended Label Strategy

Use a single `sign` detector for training, and keep the broad families only for later sorting:

- `sign`

Broad families still tracked in the normalized manifest:

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

This keeps recall high and lets review or later classifiers sort detections into
more specific sign families after capture.

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
- export a trainer-ready YOLO dataset under `data/training/exports/yolo_any_signs`

Expected raw dataset roots:

- `data/training/raw/mapillary`
- `data/training/raw/glare`

Supported annotation inputs today:

- COCO-style `.json`
- CSV files with filename plus `x1/y1/x2/y2` style box columns
- Pascal VOC `.xml`

## Next Model Step

The next practical milestone is:

1. normalize Mapillary and GLARE into one sign-heavy manifest with broad family metadata preserved
2. train a high-recall detector on a single `sign` class
3. export an edge-friendly model for the Pi
4. keep the taxonomy layer on top so archive grouping can still evolve

## Separate Classifier Path

The learned classifier should stay separate from the detector:

- detector: fast, always-on, one-class `sign` proposal model
- classifier: smaller crop model that can run later, on-demand, or in a batch pass

This avoids loading unnecessary classifier weights into the Pi's hot path while
still preserving the option to classify saved crops later.

### Starter U.S. Classifier Taxonomy

The repo now includes a starter American sign taxonomy at:

- `training/classifier_taxonomy_us.yaml`

It maps current raw labels into a conservative U.S.-oriented class set such as:

- `stop`
- `yield`
- `speed_limit_25`
- `speed_limit_35`
- `no_left_turn`
- `pedestrian_crossing`
- `chevron_left`

Unmapped global long-tail labels are intentionally skipped for now.

### Classifier Export Commands

To inspect class coverage without writing crops:

```bash
. .venv/bin/activate
python scripts/export_sign_classifier_dataset.py --summary-only
```

To export cropped classifier images:

```bash
. .venv/bin/activate
python scripts/export_sign_classifier_dataset.py
```

That writes a crop dataset under:

- `data/training/exports/classifier_us_signs`

with:

- `train/<class_name>/*.jpg`
- `val/<class_name>/*.jpg`
- `dataset.yaml`
- `crop_manifest.jsonl`
- `export_summary.json`

### Classifier Training Direction

Do not train the classifier at the same time as the long detector run if you
want to avoid Mac resource contention.

When ready, the intended training path is:

```bash
. .venv/bin/activate
yolo classify train \
  model=yolo11n-cls.pt \
  data=data/training/exports/classifier_us_signs \
  imgsz=224 \
  epochs=50 \
  batch=64 \
  device=mps
```
