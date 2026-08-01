"""deals filename and hide

Revision ID: 005_deals_filename_and_hide
Revises: 004_deals_nullable_pdf_paths
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '005_deals_filename_and_hide'
down_revision: Union[str, Sequence[str], None] = '004_deals_nullable_pdf_paths'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. TASK_fix15.md §3.

    §3.1: original_pdf_path never stored the uploaded file's own name (it's
    generated as deals/{deal_id}/original.pdf) — "Мои сделки" had nowhere to
    read a filename from. Nullable: old deals just don't have one.

    §3.2: hide (not delete) — a deal carries the legal-trail evidence (E7
    ip/ua for both parties) and must live out its 7-day retention (ADR-009)
    regardless of whether the initiator wants it in their list. Default
    false so existing rows stay visible.
    """
    op.execute("ALTER TABLE deals ADD COLUMN IF NOT EXISTS original_filename TEXT")
    op.execute(
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS hidden_by_initiator "
        "BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Downgrade schema. Drops both columns."""
    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS hidden_by_initiator")
    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS original_filename")
