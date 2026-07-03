"""signature bytea

Revision ID: 002_signature_bytea
Revises: 001_init
Create Date: 2026-07-03 14:55:08.853563

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_signature_bytea'
down_revision: Union[str, Sequence[str], None] = '001_init'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Mirrors migrations/002_signature_bytea.sql."""
    op.execute("ALTER TABLE signatures DROP COLUMN IF EXISTS gcs_path")
    op.execute("ALTER TABLE signatures ADD COLUMN IF NOT EXISTS png_bytes BYTEA")


def downgrade() -> None:
    """Downgrade schema. Restores gcs_path, drops png_bytes."""
    op.execute("ALTER TABLE signatures ADD COLUMN IF NOT EXISTS gcs_path TEXT")
    op.execute("ALTER TABLE signatures DROP COLUMN IF EXISTS png_bytes")
