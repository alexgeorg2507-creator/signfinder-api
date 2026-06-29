-- Migration 001: initial schema for SignFinder client cabinet
-- Run against both signfinder-test and signfinder-prod databases.

BEGIN;

-- ─── users ────────────────────────────────────────────────────────────────────
-- firebase_uid is the PK — no surrogate key, no join lookup needed.
CREATE TABLE IF NOT EXISTS users (
    firebase_uid  TEXT        PRIMARY KEY,
    email         TEXT        NOT NULL,
    email_verified BOOLEAN    NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── profiles ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
    user_id         TEXT        PRIMARY KEY REFERENCES users(firebase_uid) ON DELETE CASCADE,
    full_name       TEXT,
    company         TEXT,
    requisites_json JSONB       NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── signatures ───────────────────────────────────────────────────────────────
-- One signature per user (upsert on user_id).
-- gcs_path: gs://bucket/signatures/{firebase_uid}.png
CREATE TABLE IF NOT EXISTS signatures (
    user_id    TEXT        PRIMARY KEY REFERENCES users(firebase_uid) ON DELETE CASCADE,
    gcs_path   TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── parties ──────────────────────────────────────────────────────────────────
-- One "our side" template per user.
CREATE TABLE IF NOT EXISTS parties (
    user_id       TEXT        PRIMARY KEY REFERENCES users(firebase_uid) ON DELETE CASCADE,
    name          TEXT        NOT NULL DEFAULT '',
    role          TEXT        NOT NULL DEFAULT '',
    patterns_json JSONB       NOT NULL DEFAULT '[]',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── usage_counters ───────────────────────────────────────────────────────────
-- period format: 'YYYY-MM' (e.g. '2026-06')
CREATE TABLE IF NOT EXISTS usage_counters (
    user_id   TEXT    NOT NULL REFERENCES users(firebase_uid) ON DELETE CASCADE,
    period    TEXT    NOT NULL,
    doc_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period)
);

-- ─── indexes ──────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_usage_counters_user_period ON usage_counters(user_id, period);

COMMIT;
