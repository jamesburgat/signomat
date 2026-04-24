CREATE TABLE IF NOT EXISTS training_jobs (
  job_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  model_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  trip_id TEXT,
  review_state TEXT NOT NULL DEFAULT 'reviewed',
  include_false_positives INTEGER NOT NULL DEFAULT 0,
  selected_count INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_training_jobs_created ON training_jobs(created_at_utc DESC);
