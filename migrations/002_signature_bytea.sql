-- M2: store signature as bytea instead of gcs_path
-- Safe to re-run: ALTER ... IF EXISTS / IF NOT EXISTS
ALTER TABLE signatures DROP COLUMN IF EXISTS gcs_path;
ALTER TABLE signatures ADD COLUMN IF NOT EXISTS png_bytes BYTEA;
