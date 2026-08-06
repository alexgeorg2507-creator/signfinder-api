"""users terms acceptance log

Revision ID: 006_users_terms_acceptance_log
Revises: 005_deals_filename_and_hide
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '006_users_terms_acceptance_log'
down_revision: Union[str, Sequence[str], None] = '005_deals_filename_and_hide'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. TASK_fix21.md — blocking terms-acceptance gate at login.

    A journal (JSONB array), not flat terms_accepted_at/terms_version columns
    (same pattern as deals.audit_log from E7) — if the documents' version
    changes later and the user re-accepts, flat columns would just overwrite
    what they actually accepted under the old version. Appending preserves
    that history permanently. Default '[]' so existing users (everyone
    registered before this column existed) get the gate on their next login
    without any backfill or migration of their own — the gate condition is
    "empty log or last entry's version != current", which an empty array
    already satisfies.
    """
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_acceptance_log "
        "JSONB NOT NULL DEFAULT '[]'"
    )


def downgrade() -> None:
    """Downgrade schema. Drops the column."""
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS terms_acceptance_log")
