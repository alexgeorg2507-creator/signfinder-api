"""language columns on users and deals

Revision ID: 007_language_columns
Revises: 006_users_terms_acceptance_log
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '007_language_columns'
down_revision: Union[str, Sequence[str], None] = '006_users_terms_acceptance_log'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. TASK_i18n_en.md §1.

    users.language: set only on first INSERT in _get_or_create_user (from
    which URL prefix the frontend first loaded, /en/app vs /app) - never
    touched on the ON CONFLICT/upsert branch, so a later visit to /app
    without the /en prefix can't clobber a saved 'en' back to 'ru'. Default
    'ru' for existing rows (nobody registered through anything but the
    Russian UI before this).

    deals.language: copied from the initiator's users.language once, at
    create_deal time, then never changes - the counterparty on
    /sign/{token} has no account of their own to carry a language
    preference, this is the only thing to inherit from.
    """
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'ru'")
    op.execute("ALTER TABLE deals ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'ru'")


def downgrade() -> None:
    """Downgrade schema. Drops both columns."""
    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS language")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS language")
