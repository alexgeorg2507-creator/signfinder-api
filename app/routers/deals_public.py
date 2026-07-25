"""Deal Cycle (SignfinderLand v2.0.0, эпик E2): /v1/public/deals — public
endpoints, no auth, protected only by share_token possession + rate limits.

IB (THREAT_MODEL_DEAL_CYCLE.md):
- Deal identity comes ONLY from share_token in the URL — never from body
  (§3.B). DealSignRequest carries no id fields at all.
- Invalid/missing token → 404, never 403 (§3.A/§3.C — don't confirm existence).
- Rate limits: 10/min per share_token, 60/min per IP (§3.A).
- Signing is one atomic UPDATE gated on status IN ('sent','viewed') — a
  second concurrent request finds 0 rows and gets 409 (§3.E).
- DealPublicView is a strict whitelist — see its docstring (§3.F).
- CSP/X-Content-Type-Options/X-Frame-Options set in app.main for this
  prefix (§3.H).
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.db import get_pool
from app.dependencies import SignFinderDep
from app.models.deal import DealPublicView, DealSignRequest
from app.rate_limit import get_client_ip, get_share_token_key, limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Deals Public"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _fetch_deal_with_email(share_token: str) -> dict | None:
    """Deal row joined with the initiator's email — the only initiator PII
    the public API is allowed to expose (§5.5)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT d.*, u.email AS initiator_email
            FROM deals d
            JOIN users u ON u.firebase_uid = d.initiator_tenant_id
            WHERE d.share_token = $1
            """,
            share_token,
        )
    return dict(row) if row is not None else None


@router.get("/public/deals/{share_token}", response_model=DealPublicView)
@limiter.limit("10/minute", key_func=get_share_token_key)
@limiter.limit("60/minute", key_func=get_client_ip)
async def get_public_deal(request: Request, share_token: str) -> DealPublicView:
    """Metadata for the signing page. First view (status='sent') atomically
    transitions to 'viewed' with an audit_log entry carrying IP+UA."""
    deal = await _fetch_deal_with_email(share_token)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")

    if deal["status"] == "sent":
        ip = get_client_ip(request)
        ua = request.headers.get("user-agent", "")[:300]
        event = [{"event": "viewed", "at": _now().isoformat(), "ip": ip, "ua": ua}]
        pool = get_pool()
        async with pool.acquire() as conn:
            updated = await conn.fetchrow(
                """
                UPDATE deals
                SET status = 'viewed', audit_log = audit_log || $1::jsonb
                WHERE share_token = $2 AND status = 'sent'
                RETURNING status, audit_log
                """,
                event, share_token,
            )
        # updated is None only on a race with another concurrent first view —
        # harmless, that request's UPDATE already won; patch the two fields
        # that changed into the already-JOINed `deal` dict rather than
        # re-fetching (RETURNING * here wouldn't carry initiator_email anyway,
        # that's only present via the users JOIN in _fetch_deal_with_email).
        if updated is not None:
            deal["status"] = updated["status"]
            deal["audit_log"] = updated["audit_log"]

    return DealPublicView.from_row(deal)


@router.get("/public/deals/{share_token}/pdf")
@limiter.limit("10/minute", key_func=get_share_token_key)
@limiter.limit("60/minute", key_func=get_client_ip)
async def get_public_deal_pdf(request: Request, share_token: str, sf: SignFinderDep) -> Response:
    """PDF with the initiator's signature — or the final PDF once signed
    (spec §2.5: one endpoint, smart by state, not two different calls)."""
    deal = await _fetch_deal_with_email(share_token)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")

    path = deal["final_pdf_path"] or deal["initiator_signed_pdf_path"]
    pdf_bytes = sf.storage.read_bytes(path)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="PDF не найден")

    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/public/deals/{share_token}/sign", response_model=dict)
@limiter.limit("10/minute", key_func=get_share_token_key)
@limiter.limit("60/minute", key_func=get_client_ip)
async def sign_public_deal(request: Request, share_token: str, body: DealSignRequest, sf: SignFinderDep) -> dict:
    """Counterparty signs. ID comes only from share_token (URL) — DealSignRequest
    carries no identifiers at all, extra='forbid' rejects anything extra.

    Atomic UPDATE at the very end gates on status IN ('sent','viewed') — a
    concurrent/repeat POST finds 0 rows updated and gets 409 (threat model §3.E).
    Signature processing happens before that check (optimistic) since it's
    read-only against the deal row fetched here; only the final UPDATE
    decides who actually wins the race.
    """
    deal = await _fetch_deal_with_email(share_token)
    if deal is None:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    if deal["status"] not in ("sent", "viewed"):
        raise HTTPException(status_code=409, detail="Сделка уже подписана или недоступна")

    try:
        raw_png = base64.b64decode(body.signature_png_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="signature_png_b64: невалидный base64")

    from signfinder.signature import process_signature
    try:
        processed = process_signature(raw_png)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Не удалось обработать подпись: {e}")

    pdf_bytes = sf.storage.read_bytes(deal["initiator_signed_pdf_path"])
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="PDF инициатора не найден")

    anchors = deal["saved_anchors"] or []
    if not anchors:
        raise HTTPException(status_code=422, detail="Для этой сделки не сохранены места подписи контрагента")

    from signfinder.anchors import TextAnchor
    now_iso = _now().isoformat()
    anchor_objects = []
    for a in anchors:
        try:
            bbox = a.get("bbox", [0, 0, 100, 20])
            anchor_objects.append(TextAnchor(
                id=a.get("id", "a0"),
                anchor_type=a.get("anchor_type", "text_proximity"),
                anchor_level=a.get("anchor_level", 1),
                anchor_text=a.get("anchor_text", ""),
                position=a.get("position", "below"),
                offset_pt=a.get("offset_pt", 0.0),
                generated_pattern=a.get("generated_pattern", ""),
                context_before=a.get("context_before", ""),
                context_after=a.get("context_after", ""),
                page_hint=str(a.get("page_hint", "0")),
                added_by=a.get("added_by", "auto_regex"),
                added_at=a.get("added_at", now_iso),
                bbox=tuple(bbox),
            ))
        except Exception as e:
            logger.warning("Invalid saved anchor for deal %s: %s", share_token, e)

    if not anchor_objects:
        raise HTTPException(status_code=422, detail="Места подписи контрагента повреждены")

    try:
        signed_bytes = sf.sign(
            pdf_bytes, anchor_objects, processed.png_bytes,
            use_signature=True, use_marker=False,
        )
    except Exception as e:
        logger.exception("Public sign failed for share_token=%s", share_token)
        raise HTTPException(status_code=422, detail=str(e))

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")[:300]
    final_bytes = _append_legal_block(
        signed_bytes,
        deal_id=deal["id"],
        initiator_email=deal["initiator_email"],
        initiator_signed_at=deal["created_at"],
        counterparty_ip=ip,
        counterparty_ua=ua,
        counterparty_signed_at=_now(),
        signature_source=body.signature_source,
    )

    final_path = f"deals/{deal['id']}/final.pdf"
    sf.storage.write_bytes(final_path, final_bytes)

    sig_meta = {
        "source": body.signature_source,
        "ip": ip,
        "ua": ua,
        "confidence": processed.confidence,
    }
    event = [{
        "event": "signed", "at": now_iso, "ip": ip, "ua": ua,
        "signature_source": body.signature_source,
    }]

    pool = get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE deals
            SET status = 'signed',
                final_pdf_path = $1,
                counterparty_signature_meta = $2,
                audit_log = audit_log || $3::jsonb
            WHERE share_token = $4 AND status IN ('sent', 'viewed')
            RETURNING id
            """,
            final_path, sig_meta, event, share_token,
        )

    if updated is None:
        raise HTTPException(status_code=409, detail="Сделка уже подписана или недоступна")

    return {"status": "signed"}


@router.get("/public/deals/{share_token}/final-pdf")
@limiter.limit("10/minute", key_func=get_share_token_key)
@limiter.limit("60/minute", key_func=get_client_ip)
async def get_public_final_pdf(request: Request, share_token: str, sf: SignFinderDep) -> Response:
    """Final (both-sides-signed) PDF. 404 until status='signed'."""
    deal = await _fetch_deal_with_email(share_token)
    if deal is None or not deal["final_pdf_path"]:
        raise HTTPException(status_code=404, detail="Финальный PDF ещё не готов")

    pdf_bytes = sf.storage.read_bytes(deal["final_pdf_path"])
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="Финальный PDF ещё не готов")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="signed_{deal["id"]}.pdf"'},
    )


def _append_legal_block(
    pdf_bytes: bytes,
    deal_id: UUID,
    initiator_email: str,
    initiator_signed_at,
    counterparty_ip: str,
    counterparty_ua: str,
    counterparty_signed_at: datetime,
    signature_source: str,
) -> bytes:
    """Append a legal-trail page (DEAL_CYCLE_SPEC.md §7).

    TODO(E7): initiator IP/UA aren't in this block — POST /v1/deals (E1)
    never captured them (the cabinet flow that creates a Deal isn't the
    request that produced the signed PDF). Wording here is a draft, not
    legal-reviewed (spec's own caveat) — E7 owns the final text + capturing
    initiator IP/UA at Deal-creation time if that's still wanted.
    """
    import fitz

    ua_short = (counterparty_ua or "")[:120]
    text = (
        "─────────────────────────────────────────────────────────\n"
        "Электронная подпись сформирована через SignFinder (signfinder.app).\n"
        "Простая электронная подпись (ПЭП) по соглашению сторон.\n\n"
        f"Инициатор: {initiator_email}\n"
        f"  Подписано: {initiator_signed_at.astimezone(timezone.utc).isoformat()}\n\n"
        "Контрагент подписал по временной ссылке:\n"
        f"  Подписано: {counterparty_signed_at.isoformat()}, IP {counterparty_ip}, UA {ua_short}\n"
        f"  Способ ввода подписи: {signature_source}\n\n"
        f"ID сделки: {deal_id}\n"
        "─────────────────────────────────────────────────────────"
    )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc.new_page()
        page.insert_textbox(
            fitz.Rect(50, 50, page.rect.width - 50, page.rect.height - 50),
            text, fontsize=10, fontname="helv",
        )
        out = doc.tobytes()
    finally:
        doc.close()
    return out
