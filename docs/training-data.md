# Training Data Plan

Signomat now defaults to the learned detector and classifier on the Pi. This
document tracks the training-data stack behind that broader, recall-heavy model.

## Selected Datasets

- `Mapillary Traffic Sign Dataset`
  - Role: primary broad-coverage dataset
  - Why: best first source for diverse sign appearances and large sign-class coverage
  - Source: https://www.mapillary.com/dataset/trafficsign

- `GLARE`
  - Role: robustness supplement
  - Why: adds hard examples under strong glare and windshield-style reflections
  - Source: https://arxiv.org/abs/2209.08716

- `BDD100K Detection`
  - Role: U.S.-heavy full-scene detector supplement
  - Why: adds many road-scene boxes for generic `traffic sign`, which directly targets detector recall
  - Source: https://bdd-data.berkeley.edu/

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

## Runtime Capture Policy

The Pi runtime now keeps normal drives focused on higher-confidence detections:

- `save_unknown_signs: true`
- `save_crops: false`
- `min_box_area: 900`
- `min_detector_confidence: 0.6`
- `min_classifier_confidence: 0.75`

Unknown signs that clear the detector threshold are still saved for collection;
full clean and annotated frames remain available for review, but sign crop files
and crop thumbnails are not written during normal drives. YOLO detections smaller
than `min_box_area` are filtered before classification, which removes tiny
far-field or speck-like boxes;
lower thresholds should be used only for intentional review or training-data
collection runs. The broader detector/classifier work still supports:

- mock detector/classifier support for sign-like color proposals such as `green`,
  `white`, and `orange`
- broad raw labels such as:
  - `guide_sign`
  - `regulatory_rect`
  - `service_sign`
  - `work_zone_sign`

The live Pi path is learned-model first; the mock detector/classifier path is
retained only for mock/dev runs and explicit simulator experiments.

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
- `data/training/raw/bdd100k`

Supported annotation inputs today:

- COCO-style `.json`
- BDD100K Detection `.json`
- CSV files with filename plus `x1/y1/x2/y2` style box columns
- Pascal VOC `.xml`
- Mapillary Traffic Sign Dataset per-image `.json`

### BDD100K Detector Supplement

BDD100K is the best next data source for improving detector recall because it
adds full driving scenes with a generic `traffic sign` detection class. Download
the 100K images and Detection 2020 labels from the official BDD100K site after
accepting their terms, then arrange them as:

```text
data/training/raw/bdd100k/images/100k/train/*.jpg
data/training/raw/bdd100k/images/100k/val/*.jpg
data/training/raw/bdd100k/annotations/train/*.json
data/training/raw/bdd100k/annotations/val/*.json
```

The normalizer also supports the older single-file Detection JSON layout, but
the per-image `train/*.json` and `val/*.json` layout matches the `100k-2`
download. It keeps only BDD labels whose category is `traffic sign`, then the
YOLO `any_sign` export collapses them into the detector's single `sign` class.

## Next Model Step

The next practical milestone is:

1. normalize Mapillary and GLARE into one sign-heavy manifest with broad family metadata preserved
2. train a high-recall detector on a single `sign` class
3. export an edge-friendly model for the Pi
4. keep the taxonomy layer on top so archive grouping can still evolve

## Separate Classifier Path

The learned classifier stays architecturally separate from the detector:

- detector: fast, always-on, one-class `sign` proposal model
- classifier: smaller crop model that runs on detector crops and can be disabled with `SIGNOMAT_CLASSIFIER_BACKEND=none`

The default Pi config uses the learned NCNN exports in `models/`. If the ML
runtime is missing or the model path is unavailable, startup should fail loudly
instead of silently switching to the mock detector/classifier implementation.

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

### Data-Driven Classifier Export

For the broad raw-label classifier, generate a taxonomy from the normalized
manifest and export crops with:

```bash
. .venv/bin/activate
python scripts/generate_classifier_taxonomy_from_manifest.py \
  --min-count 100 \
  --output training/classifier_taxonomy_dataset.yaml
python scripts/export_sign_classifier_dataset.py \
  --taxonomy training/classifier_taxonomy_dataset.yaml \
  --output-dir data/training/exports/classifier_dataset_raw_min100
```

### Classifier Training Direction

Do not train the classifier at the same time as the long detector run if you
want to avoid Mac resource contention.

When ready, the intended training path is:

```bash
. .venv/bin/activate
yolo classify train \

### Archive Review To Detector Dataset

Once you have reviewed detections in the archive site and created a detector
training draft, you can turn that site export directly into a YOLO dataset with:

```bash
. .venv/bin/activate
python scripts/export_yolo_detection_dataset.py \
  --archive-export-url "https://signomat-api.example.workers.dev/admin/training/jobs/job_x/export" \
  --output-dir data/training/exports/job_x \
  --image-mode copy
```

That archive mode will:

- download the reviewed detection export JSON from the Worker
- download the referenced frame images into a local cache
- write YOLO labels for confirmed signs
- write empty label files for `false_positive` review rows so detector training
  can learn negative frames from your own drives
  model=yolo11n-cls.pt \
  data=data/training/exports/classifier_dataset_raw_min100 \
  imgsz=224 \
  epochs=50 \
  batch=64 \
  device=mps
```

The deployable checkpoints and NCNN exports are tracked under `models/`.
