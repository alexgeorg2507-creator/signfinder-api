"""init

Revision ID: 001_init
Revises: 
Create Date: 2026-07-03 14:55:05.060942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_init'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Mirrors migrations/001_init.sql."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            firebase_uid  TEXT        PRIMARY KEY,
            email         TEXT        NOT NULL,
            email_verified BOOLEAN    NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id         TEXT        PRIMARY KEY REFERENCES users(firebase_uid) ON DELETE CASCADE,
            full_name       TEXT,
            company         TEXT,
            requisites_json JSONB       NOT NULL DEFAULT '{}',
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS signatures (
            user_id    TEXT        PRIMARY KEY REFERENCES users(firebase_uid) ON DELETE CASCADE,
            gcs_path   TEXT        NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS parties (
            user_id       TEXT        PRIMARY KEY REFERENCES users(firebase_uid) ON DELETE CASCADE,
            name          TEXT        NOT NULL DEFAULT '',
            role          TEXT        NOT NULL DEFAULT '',
            patterns_json JSONB       NOT NULL DEFAULT '[]',
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS usage_counters (
            user_id   TEXT    NOT NULL REFERENCES users(firebase_uid) ON DELETE CASCADE,
            period    TEXT    NOT NULL,
            doc_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, period)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_counters_user_period "
        "ON usage_counters(user_id, period)"
    )


def downgrade() -> None:
    """Downgrade schema. Drops tables in reverse FK order."""
    op.execute("DROP TABLE IF EXISTS usage_counters")
    op.execute("DROP TABLE IF EXISTS parties")
    op.execute("DROP TABLE IF EXISTS signatures")
    op.execute("DROP TABLE IF EXISTS profiles")
    op.execute("DROP TABLE IF EXISTS users")
