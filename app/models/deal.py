"""Pydantic-схемы для /v1/deals (SignfinderLand v2.0.0 Deal Cycle).

Приватные модели инициатора (эпик E1) — за Firebase JWT, см.
app/routers/deals.py. Публичные модели контрагента (эпик E2) —
DealPublicView, DealSignRequest, без auth, см. app/routers/deals_public.py.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

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


# ── Публичные модели (эпик E2, без auth) ────────────────────────────────────


class DealPublicView(BaseModel):
    """GET /v1/public/deals/{share_token} — то, что видит анонимный контрагент.

    Строгий whitelist (DEAL_CYCLE_SPEC.md §5.5, THREAT_MODEL_DEAL_CYCLE.md
    §3.F) — никогда initiator_tenant_id/initiator_firebase_uid, профиль
    инициатора, другие сделки, якоря инициатора, полный audit_log,
    storage-пути. Тест: test_public_view_no_sensitive_fields.
    """
    model_config = ConfigDict(extra="forbid")
    initiator_email: str
    status: DealStatus
    expires_at: datetime
    # saved_anchors (E1) уже хранит только якоря контрагента — /v1/me/analyze
    # отдаёт их отдельным полем counterparty_anchors, фильтровать по
    # party_role здесь нечего, см. TASK_deal_cycle_E2.md.
    counterparty_anchors: list[dict[str, Any]]
    has_pdf: bool
    has_final_pdf: bool

    @classmethod
    def from_row(cls, row: dict) -> "DealPublicView":
        return cls(
            initiator_email=row["initiator_email"],
            status=row["status"],
            expires_at=row["expires_at"],
            counterparty_anchors=row["saved_anchors"] or [],
            has_pdf=bool(row["initiator_signed_pdf_path"]),
            has_final_pdf=row["final_pdf_path"] is not None,
        )


class DealSignRequest(BaseModel):
    """POST /v1/public/deals/{share_token}/sign payload.

    ID сделки — только из URL (share_token), никогда из body (DEAL_CYCLE_SPEC.md
    §5.7, THREAT_MODEL_DEAL_CYCLE.md §3.B) — эта схема физически не содержит
    никаких полей-идентификаторов, extra='forbid' не пропустит лишние.
    """
    model_config = ConfigDict(extra="forbid")
    signature_png_b64: str
    consent_pep: bool
    signature_source: Literal["camera", "file", "canvas"]

    @field_validator("consent_pep")
    @classmethod
    def must_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("ПЭП-согласие обязательно")
        return v
