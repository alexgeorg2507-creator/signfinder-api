"""Deal Cycle (SignfinderLand v2.0.0, эпик E1): /v1/deals — private endpoints,
all require Firebase JWT.

IB (ADR-007):
- tenant_id (firebase_uid) ONLY from verified JWT, never from body/URL
- Every SQL filters by initiator_tenant_id from token
- 404 instead of 403 for other-user resources (threat model §3.C)
- extra='forbid' on all Pydantic input models
- mark-shared is an atomic UPDATE gated on status='draft' (threat model §3.E)

Public endpoints (/v1/public/deals/*, no auth, by share_token) are E2 —
not implemented here. See DEAL_CYCLE_SPEC.md §8.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.db import get_pool
from app.dependencies import SignFinderDep
from app.models.deal import Deal, DealCreate, DealListItem, MarkSharedRequest
from app.routers.me import UserDep, _get_usage_count, _MONTHLY_LIMIT
from app.utils.share_token import generate_share_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Deals"])

_DEAL_TTL_DAYS = 7
_MAX_SHARE_TOKEN_RETRIES = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decode_pdf_b64(b64: str, field_name: str) -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail=f"{field_name}: невалидный base64")


@router.post("/deals", response_model=Deal, status_code=201)
async def create_deal(body: DealCreate, user: UserDep, sf: SignFinderDep) -> Deal:
    """Create a Deal from an already-signed (by the initiator) contract.

    tenant_id comes only from the JWT (UserDep) — never from the body.
    Document processing (/v1/me/analyze, /v1/me/sign) already happened and was
    already counted against the monthly usage limit; this only checks the
    limit isn't exceeded, it does not increment it a second time.
    """
    tenant_id = user["firebase_uid"]

    count = await _get_usage_count(tenant_id)
    if count >= _MONTHLY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Лимит исчерпан: {_MONTHLY_LIMIT} документов в месяц на бесплатном тарифе.",
        )

    original_bytes = _decode_pdf_b64(body.original_pdf_b64, "original_pdf_b64")
    signed_bytes = _decode_pdf_b64(body.initiator_signed_pdf_b64, "initiator_signed_pdf_b64")

    deal_id = uuid4()
    original_path = f"deals/{deal_id}/original.pdf"
    signed_path = f"deals/{deal_id}/initiator_signed.pdf"
    sf.storage.write_bytes(original_path, original_bytes)
    sf.storage.write_bytes(signed_path, signed_bytes)

    now = _now()
    expires_at = now + timedelta(days=_DEAL_TTL_DAYS)
    audit_log = [{"event": "created", "at": now.isoformat(), "actor": "initiator"}]

    pool = get_pool()
    row = None
    async with pool.acquire() as conn:
        for attempt in range(_MAX_SHARE_TOKEN_RETRIES):
            share_token = generate_share_token()
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO deals (
                        id, initiator_tenant_id, created_at, expires_at, status,
                        share_token, original_pdf_path, initiator_signed_pdf_path,
                        saved_anchors, audit_log
                    )
                    VALUES ($1, $2, $3, $4, 'draft', $5, $6, $7, $8, $9)
                    RETURNING *
                    """,
                    deal_id, tenant_id, now, expires_at,
                    share_token, original_path, signed_path,
                    body.saved_anchors, audit_log,
                )
                break
            except asyncpg.UniqueViolationError:
                logger.warning(
                    "share_token collision on attempt %d for deal %s", attempt + 1, deal_id
                )
                continue

    if row is None:
        logger.error("Failed to generate a unique share_token after %d attempts", _MAX_SHARE_TOKEN_RETRIES)
        raise HTTPException(status_code=500, detail="Не удалось создать сделку, попробуйте ещё раз")

    return Deal.from_row(dict(row))


@router.get("/deals", response_model=list[DealListItem])
async def list_deals(
    user: UserDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[DealListItem]:
    """List this initiator's deals, newest first."""
    tenant_id = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM deals
            WHERE initiator_tenant_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            tenant_id, limit, offset,
        )
    return [DealListItem.from_row(dict(r)) for r in rows]


@router.get("/deals/{deal_id}", response_model=Deal)
async def get_deal(deal_id: UUID, user: UserDep) -> Deal:
    """Deal details + audit log. 404 (not 403) if owned by another tenant —
    doesn't confirm to the caller whether the deal exists at all."""
    tenant_id = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM deals WHERE id = $1 AND initiator_tenant_id = $2",
            deal_id, tenant_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return Deal.from_row(dict(row))


@router.post("/deals/{deal_id}/mark-shared", response_model=Deal)
async def mark_shared(deal_id: UUID, body: MarkSharedRequest, user: UserDep) -> Deal:
    """Mark that the initiator pressed one of the 3 share buttons.

    Atomic UPDATE gated on status='draft' (threat model §3.E) — a concurrent
    or repeat call finds 0 rows updated and gets 409, not a silent overwrite.
    """
    tenant_id = user["firebase_uid"]
    now = _now()
    event = [{"event": "sent", "at": now.isoformat(), "channel": body.channel.value}]

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE deals
            SET status = 'sent',
                share_channel_used = $1,
                audit_log = audit_log || $2::jsonb
            WHERE id = $3 AND initiator_tenant_id = $4 AND status = 'draft'
            RETURNING *
            """,
            body.channel.value, event, deal_id, tenant_id,
        )
        if row is None:
            exists = await conn.fetchval(
                "SELECT 1 FROM deals WHERE id = $1 AND initiator_tenant_id = $2",
                deal_id, tenant_id,
            )
            if not exists:
                raise HTTPException(status_code=404, detail="Сделка не найдена")
            raise HTTPException(status_code=409, detail="Сделка уже передана или в другом статусе")

    return Deal.from_row(dict(row))


@router.get("/deals/{deal_id}/final-pdf")
async def get_final_pdf(deal_id: UUID, user: UserDep, sf: SignFinderDep) -> Response:
    """Download the final (counterparty-signed) PDF. 404 until status=signed."""
    tenant_id = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        final_pdf_path = await conn.fetchval(
            "SELECT final_pdf_path FROM deals WHERE id = $1 AND initiator_tenant_id = $2",
            deal_id, tenant_id,
        )
    if not final_pdf_path:
        raise HTTPException(status_code=404, detail="Финальный PDF ещё не готов")

    pdf_bytes = sf.storage.read_bytes(final_pdf_path)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="Финальный PDF ещё не готов")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="signed_{deal_id}.pdf"'},
    )
