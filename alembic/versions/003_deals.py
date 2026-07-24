"""deals

Revision ID: 003_deals
Revises: 002_signature_bytea
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_deals'
down_revision: Union[str, Sequence[str], None] = '002_signature_bytea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. v2.0.0 Deal Cycle — see DEAL_CYCLE_SPEC.md §4.

    NOTE (spec correction): DEAL_CYCLE_SPEC.md §4 originally wrote
    `initiator_user_id UUID REFERENCES users(id)`. Neither `users.id` nor
    `users.tenant_id` exist in the real schema (see 001_init.py) — the only
    PK is `users.firebase_uid TEXT`, and every other table (profiles,
    parties, signatures, usage_counters) references it via a `user_id`
    column. `initiator_tenant_id` keeps the forward-looking ADR-006 name
    (tenant_id == user_id for personal accounts) but the FK target is fixed
    to point at the column that actually exists.
    """
    op.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id                          UUID        PRIMARY KEY,
            initiator_tenant_id         TEXT        NOT NULL REFERENCES users(firebase_uid),
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at                  TIMESTAMPTZ NOT NULL,
            status                      TEXT        NOT NULL,
            share_token                 VARCHAR(32) UNIQUE NOT NULL,
            share_channel_used          TEXT,
            original_pdf_path           TEXT        NOT NULL,
            initiator_signed_pdf_path   TEXT        NOT NULL,
            final_pdf_path              TEXT,
            saved_anchors               JSONB       NOT NULL,
            audit_log                   JSONB       NOT NULL DEFAULT '[]',
            counterparty_signature_meta JSONB
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_deals_initiator "
        "ON deals(initiator_tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_deals_share_token "
        "ON deals(share_token)"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_deals_expires ON deals(expires_at)
          WHERE status IN ('draft','sent','viewed')
    """)


def downgrade() -> None:
    """Downgrade schema. Drops deals table and its indexes."""
    op.execute("DROP INDEX IF EXISTS ix_deals_expires")
    op.execute("DROP INDEX IF EXISTS ix_deals_share_token")
    op.execute("DROP INDEX IF EXISTS ix_deals_initiator")
    op.execute("DROP TABLE IF EXISTS deals")
