# SQLite Schema

## Tables

- `trips`: one row per drive/session.
- `detections`: persisted detection events with taxonomy output, GPS, frame assets, and dedupe info.
- `gps_points`: full breadcrumb trail sampled throughout active trips.
- `video_segments`: chunked local recordings linked to trips.
- `upload_queue`: durable offline-first sync backlog.
- `device_events`: service lifecycle, warnings, low-storage events, and control actions.
- `model_versions`: detector/classifier/taxonomy versions used during runs.
- `taxonomy_mapping`: active taxonomy config snapshot stored in SQLite for replay and auditing.
- `settings`: device-local settings and current runtime flags.

## Migration Strategy

- Schema migrations live in `pi/migrations/`.
- A lightweight migration runner records applied filenames in `schema_migrations`.
- The initial migration creates the schema and indexes for recent trip, GPS, and detection lookups.

## Detection Record Additions

In addition to the requested core fields, Phase 1 adds:

- `annotated_thumbnail_path`
- `clean_thumbnail_path`
- `sign_crop_thumbnail_path`
- `raw_detector_label`
- `raw_classifier_label`

These keep the public archive fast and preserve the detector/classifier outputs separately from the remapped taxonomy.

