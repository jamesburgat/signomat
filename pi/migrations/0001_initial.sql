CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trips (
  trip_id TEXT PRIMARY KEY,
  started_at_utc TEXT NOT NULL,
  ended_at_utc TEXT,
  status TEXT NOT NULL,
  recording_enabled INTEGER NOT NULL DEFAULT 0,
  inference_enabled INTEGER NOT NULL DEFAULT 0,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS detections (
  event_id TEXT PRIMARY KEY,
  trip_id TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  gps_lat REAL,
  gps_lon REAL,
  gps_speed REAL,
  heading REAL,
  category_id TEXT NOT NULL,
  category_label TEXT NOT NULL,
  specific_label TEXT,
  grouping_mode TEXT NOT NULL,
  raw_detector_label TEXT,
  raw_classifier_label TEXT,
  detector_confidence REAL,
  classifier_confidence REAL,
  bbox_left INTEGER,
  bbox_top INTEGER,
  bbox_right INTEGER,
  bbox_bottom INTEGER,
  annotated_frame_path TEXT,
  clean_frame_path TEXT,
  sign_crop_path TEXT,
  annotated_thumbnail_path TEXT,
  clean_thumbnail_path TEXT,
  sign_crop_thumbnail_path TEXT,
  video_segment_id TEXT,
  video_timestamp_offset_ms INTEGER,
  dedupe_group_id TEXT,
  suppressed_nearby_count INTEGER NOT NULL DEFAULT 0,
  upload_state TEXT NOT NULL DEFAULT 'pending',
  review_state TEXT NOT NULL DEFAULT 'unreviewed',
  notes TEXT,
  FOREIGN KEY(trip_id) REFERENCES trips(trip_id),
  FOREIGN KEY(video_segment_id) REFERENCES video_segments(video_segment_id)
);

CREATE TABLE IF NOT EXISTS gps_points (
  gps_point_id TEXT PRIMARY KEY,
  trip_id TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  lat REAL,
  lon REAL,
  speed REAL,
  heading REAL,
  altitude REAL,
  fix_quality TEXT,
  source TEXT,
  FOREIGN KEY(trip_id) REFERENCES trips(trip_id)
);

CREATE TABLE IF NOT EXISTS video_segments (
  video_segment_id TEXT PRIMARY KEY,
  trip_id TEXT NOT NULL,
  start_timestamp_utc TEXT NOT NULL,
  end_timestamp_utc TEXT,
  file_path TEXT NOT NULL,
  file_size INTEGER NOT NULL DEFAULT 0,
  duration_sec REAL NOT NULL DEFAULT 0,
  upload_state TEXT NOT NULL DEFAULT 'pending',
  FOREIGN KEY(trip_id) REFERENCES trips(trip_id)
);

CREATE TABLE IF NOT EXISTS upload_queue (
  queue_id TEXT PRIMARY KEY,
  item_type TEXT NOT NULL,
  local_path TEXT,
  related_table TEXT,
  related_id TEXT,
  payload_json TEXT,
  state TEXT NOT NULL DEFAULT 'pending',
  retry_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_utc TEXT,
  last_error TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_events (
  device_event_id TEXT PRIMARY KEY,
  timestamp_utc TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT
);

CREATE TABLE IF NOT EXISTS model_versions (
  model_version_id TEXT PRIMARY KEY,
  component TEXT NOT NULL,
  version_label TEXT NOT NULL,
  source TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taxonomy_mapping (
  mapping_id TEXT PRIMARY KEY,
  raw_label TEXT NOT NULL,
  category_id TEXT NOT NULL,
  category_label TEXT NOT NULL,
  specific_label TEXT,
  grouping_mode TEXT NOT NULL,
  source_config_version TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_detections_trip_ts ON detections(trip_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_gps_trip_ts ON gps_points(trip_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_video_trip_ts ON video_segments(trip_id, start_timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_upload_queue_state ON upload_queue(state, next_attempt_utc);
