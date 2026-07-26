"""Internal /internal/deals/* endpoints — Deal Cycle E5 retention/cleanup.

Protected by CronKeyDep (X-Deals-Cron-Key header, same API_KEY secret as
ApiKeyDep elsewhere) — NOT ApiKeyDep/Authorization, see CronKeyDep's
docstring in app/dependencies.py for why: Cloud Scheduler HTTP targets
reserve the "Authorization" header name for their own oauth_token/oidc_token
oneof and silently drop a manually-set value there
(TASK_e5_scheduler_auth_followup.md).

Called by Cloud Scheduler jobs (see monitoring/setup_deals_retention_cron.py).
Not registered under /v1 — Cloud Scheduler hits the raw Cloud Run URL directly,
bypassing the Firebase Hosting /api-prefix-stripping middleware entirely (that
middleware only strips a prefix Hosting itself adds on proxied requests).

DEAL_CYCLE_SPEC.md §8 E5. Owner decision (2026-07-26): signed deals' files are
purged after 7 days same as unfinished ones, without exception — only the
status transition to 'expired' is skipped for them, the row stays as an
audit record of a completed deal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from app.db import get_pool
from app.dependencies import CronKeyDep, SignFinderDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Internal"])

_PDF_PATH_COLUMNS = ("original_pdf_path", "initiator_signed_pdf_path", "final_pdf_path")
_UNFINISHED_STATUSES = ("draft", "sent", "viewed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/internal/deals/expire-sweep", include_in_schema=False)
async def expire_sweep(_: CronKeyDep, sf: SignFinderDep) -> dict:
    """Hourly: purge files for deals past expires_at, mark unfinished ones expired.

    WHERE expires_at < now() AND at least one PDF path still set — idempotent
    by construction: once a row's three paths are all NULL (this endpoint's
    own UPDATE), it no longer matches on a repeat/retried call.
    """
    pool = get_pool()
    processed = 0
    files_deleted = 0
    now_iso = _now().isoformat()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, status, original_pdf_path, initiator_signed_pdf_path, final_pdf_path
            FROM deals
            WHERE expires_at < NOW()
              AND (original_pdf_path IS NOT NULL
                   OR initiator_signed_pdf_path IS NOT NULL
                   OR final_pdf_path IS NOT NULL)
            """
        )

        for row in rows:
            for col in _PDF_PATH_COLUMNS:
                path = row[col]
                if path is not None and sf.storage.delete(path):
                    files_deleted += 1

            if row["status"] in _UNFINISHED_STATUSES:
                event = [{"event": "expired", "at": now_iso}]
                await conn.execute(
                    """
                    UPDATE deals
                    SET status = 'expired',
                        original_pdf_path = NULL,
                        initiator_signed_pdf_path = NULL,
                        final_pdf_path = NULL,
                        audit_log = audit_log || $2::jsonb
                    WHERE id = $1
                    """,
                    row["id"], event,
                )
            else:
                # status == 'signed' (or already 'rejected' — files can still
                # be present for a rejected deal, nothing in this codebase
                # currently sets that status, but the filter above doesn't
                # exclude it): status untouched, just note the purge.
                event = [{"event": "files_purged", "at": now_iso}]
                await conn.execute(
                    """
                    UPDATE deals
                    SET original_pdf_path = NULL,
                        initiator_signed_pdf_path = NULL,
                        final_pdf_path = NULL,
                        audit_log = audit_log || $2::jsonb
                    WHERE id = $1
                    """,
                    row["id"], event,
                )
            processed += 1

    logger.info("expire-sweep: processed=%d files_deleted=%d", processed, files_deleted)
    return {"processed": processed, "files_deleted": files_deleted}


@router.post("/internal/deals/purge-old", include_in_schema=False)
async def purge_old(_: CronKeyDep) -> dict:
    """Daily: hard-delete deal rows whose files were purged 30+ days ago.

    No status filter — expire-sweep already unconditionally nulled every
    deal's PDF paths (signed included) at the 7-day mark, so by the time a
    row is 30 days past expires_at its files are already long gone.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetch(
            "DELETE FROM deals WHERE expires_at + interval '30 days' < NOW() RETURNING id"
        )

    logger.info("purge-old: deleted=%d", len(deleted))
    return {"deleted": len(deleted)}
