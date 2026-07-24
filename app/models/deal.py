"""Pydantic-схемы для /v1/deals (SignfinderLand v2.0.0 Deal Cycle, эпик E1).

Приватные модели инициатора — за Firebase JWT (см. app/routers/deals.py).
Публичная модель для контрагента (DealPublicView) и DealSignRequest —
эпик E2, здесь намеренно не создаются (см. DEAL_CYCLE_SPEC.md §8).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

_SHARE_URL_BASE = "https://signfinder.app/sign"


class DealStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    SIGNED = "signed"
    EXPIRED = "expired"
    REJECTED = "rejected"


class ShareChannel(str, Enum):
    COPY_LINK = "copy_link"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class DealCreate(BaseModel):
    """POST /v1/deals payload."""
    model_config = ConfigDict(extra="forbid")
    original_pdf_b64: str
    initiator_signed_pdf_b64: str
    saved_anchors: list[dict[str, Any]]  # тип якорей — как отдаёт /v1/me/analyze


class Deal(BaseModel):
    """GET /v1/deals/{id} — для инициатора, полная модель."""
    model_config = ConfigDict(extra="forbid")
    id: UUID
    initiator_tenant_id: str
    created_at: datetime
    expires_at: datetime
    status: DealStatus
    share_token: str
    share_url: str
    share_channel_used: Optional[ShareChannel] = None
    audit_log: list[dict[str, Any]]
    has_final_pdf: bool

    @classmethod
    def from_row(cls, row: dict) -> "Deal":
        return cls(
            id=row["id"],
            initiator_tenant_id=row["initiator_tenant_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            share_token=row["share_token"],
            share_url=f"{_SHARE_URL_BASE}/{row['share_token']}",
            share_channel_used=row["share_channel_used"],
            audit_log=row["audit_log"] or [],
            has_final_pdf=row["final_pdf_path"] is not None,
        )


class DealListItem(BaseModel):
    """GET /v1/deals — компактная версия для списка."""
    model_config = ConfigDict(extra="forbid")
    id: UUID
    created_at: datetime
    expires_at: datetime
    status: DealStatus
    share_channel_used: Optional[ShareChannel] = None

    @classmethod
    def from_row(cls, row: dict) -> "DealListItem":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            share_channel_used=row["share_channel_used"],
        )


class MarkSharedRequest(BaseModel):
    """POST /v1/deals/{id}/mark-shared payload."""
    model_config = ConfigDict(extra="forbid")
    channel: ShareChannel
