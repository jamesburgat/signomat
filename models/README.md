# Signomat Model Artifacts

This directory contains small deployable model checkpoints for Pi-side testing.

- `sign_detector_yolo11n_any_sign.pt`: one-class `sign` detector trained on the `yolo_any_signs` export.
- `sign_classifier_yolo11n_raw_min100.pt`: crop classifier trained on the data-driven 178-class raw-label taxonomy.

The classifier label taxonomy is tracked in `training/classifier_taxonomy_dataset.yaml`.

The full training run directories under `runs/` and the generated datasets under `data/` are intentionally not tracked.
