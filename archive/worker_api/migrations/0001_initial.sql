CREATE TABLE IF NOT EXISTS ingest_receipts (
  receipt_id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  uploaded_at_utc TEXT NOT NULL,
  request_sha256 TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trips (
  trip_id TEXT PRIMARY KEY,
  started_at_utc TEXT NOT NULL,
  ended_at_utc TEXT,
  status TEXT NOT NULL,
  recording_enabled INTEGER NOT NULL DEFAULT 0,
  inference_enabled INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_segments (
  video_segment_id TEXT PRIMARY KEY,
  trip_id TEXT NOT NULL,
  start_timestamp_utc TEXT NOT NULL,
  end_timestamp_utc TEXT,
  media_bucket TEXT,
  media_key TEXT,
  file_size INTEGER,
  duration_sec REAL,
  updated_at_utc TEXT NOT NULL
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
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detections (
  event_id TEXT PRIMARY KEY,
  trip_id TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  category_id TEXT NOT NULL,
  category_label TEXT NOT NULL,
  specific_label TEXT,
  grouping_mode TEXT NOT NULL,
  raw_detector_label TEXT,
  raw_classifier_label TEXT,
  detector_confidence REAL,
  classifier_confidence REAL,
  gps_lat REAL,
  gps_lon REAL,
  gps_speed REAL,
  heading REAL,
  bbox_left INTEGER,
  bbox_top INTEGER,
  bbox_right INTEGER,
  bbox_bottom INTEGER,
  annotated_frame_bucket TEXT,
  annotated_frame_key TEXT,
  clean_frame_bucket TEXT,
  clean_frame_key TEXT,
  sign_crop_bucket TEXT,
  sign_crop_key TEXT,
  annotated_thumb_bucket TEXT,
  annotated_thumb_key TEXT,
  clean_thumb_bucket TEXT,
  clean_thumb_key TEXT,
  sign_crop_thumb_bucket TEXT,
  sign_crop_thumb_key TEXT,
  video_segment_id TEXT,
  video_timestamp_offset_ms INTEGER,
  dedupe_group_id TEXT,
  suppressed_nearby_count INTEGER NOT NULL DEFAULT 0,
  review_state TEXT NOT NULL DEFAULT 'unreviewed',
  notes TEXT,
  updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_detections_trip_ts ON detections(trip_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_detections_category_ts ON detections(category_label, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_gps_trip_ts ON gps_points(trip_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_video_trip_ts ON video_segments(trip_id, start_timestamp_utc DESC);
