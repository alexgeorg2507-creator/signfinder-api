"""deals nullable pdf paths

Revision ID: 004_deals_nullable_pdf_paths
Revises: 003_deals
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '004_deals_nullable_pdf_paths'
down_revision: Union[str, Sequence[str], None] = '003_deals'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. v2.0.0 Deal Cycle E5 — see DEAL_CYCLE_SPEC.md §8 E5.

    Retention cleanup (expire-sweep) nulls out all three PDF path columns
    once a deal's files are purged, including for `signed` deals (owner
    decision 2026-07-26: files are purged after 7 days without exception,
    the row/status is kept as an audit record). `original_pdf_path` and
    `initiator_signed_pdf_path` were `NOT NULL` since 003_deals (always
    populated at creation, before Deal Cycle had any file-cleanup step) —
    relaxed here so the sweep's UPDATE doesn't violate the constraint.
    """
    op.execute("ALTER TABLE deals ALTER COLUMN original_pdf_path DROP NOT NULL")
    op.execute("ALTER TABLE deals ALTER COLUMN initiator_signed_pdf_path DROP NOT NULL")


def downgrade() -> None:
    """Downgrade schema. Restores NOT NULL — fails if any row already has
    NULLs in these columns (expected: only rows swept by expire-sweep)."""
    op.execute("ALTER TABLE deals ALTER COLUMN initiator_signed_pdf_path SET NOT NULL")
    op.execute("ALTER TABLE deals ALTER COLUMN original_pdf_path SET NOT NULL")
