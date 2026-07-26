"""Internal /internal/deals/* — Deal Cycle E5 retention/cleanup.

Deal rows aren't covered by conftest's autouse `_cleanup_test_users` — see
test_deals_crud.py's module docstring for why this file needs its own
`_cleanup_test_deals` fixture (FK to users(firebase_uid), teardown order).

These endpoints check CronKeyDep (X-Deals-Cron-Key), not Firebase auth and
not Authorization: Bearer — see app/dependencies.py::verify_cron_key for why
not the latter (Cloud Scheduler reserves that header name for its own OAuth/
OIDC oneof and silently drops a manually-set value). `client` (plain,
unauthenticated TestClient) is what calls them; `client_as(USER_A)` is only
used to create the deal via the real, Firebase-auth-protected /v1/deals.
"""
from __future__ import annotations

import base64
import json

import pytest

from app.dependencies import get_signfinder
from tests.conftest import USER_A

_CRON_KEY_HEADERS = {"X-Deals-Cron-Key": "test_key_123"}

_FAKE_ORIGINAL_PDF_B64 = base64.b64encode(b"%PDF-1.4 fake original").decode()
_FAKE_SIGNED_PDF_B64 = base64.b64encode(b"%PDF-1.4 fake initiator-signed").decode()
_SAVED_ANCHORS = [
    {
        "id": "a1", "anchor_type": "text_proximity", "anchor_level": 1,
        "anchor_text": "Контрагент", "position": "below", "offset_pt": 0.0,
        "generated_pattern": "", "context_before": "", "context_after": "",
        "page_hint": "0", "added_by": "auto_regex", "bbox": [0, 0, 100, 20],
    },
]


def _deal_payload() -> dict:
    return {
        "original_pdf_b64": _FAKE_ORIGINAL_PDF_B64,
        "initiator_signed_pdf_b64": _FAKE_SIGNED_PDF_B64,
        "saved_anchors": _SAVED_ANCHORS,
    }


async def _delete_test_deals(conn) -> None:
    await conn.execute("DELETE FROM deals WHERE initiator_tenant_id=$1", USER_A)


@pytest.fixture(autouse=True)
def _cleanup_test_deals(db_exec):
    db_exec(_delete_test_deals)
    yield
    db_exec(_delete_test_deals)


def _create_deal(client_as) -> dict:
    r = client_as(USER_A).post("/v1/deals", json=_deal_payload())
    assert r.status_code == 201
    return r.json()


async def _backdate_expiry(conn, deal_id: str, *, hours: int = 0, days: int = 0) -> None:
    await conn.execute(
        "UPDATE deals SET expires_at = NOW() - ($2 * interval '1 hour') - ($3 * interval '1 day') "
        "WHERE id = $1",
        deal_id, hours, days,
    )


async def _set_status(conn, deal_id: str, status: str) -> None:
    await conn.execute("UPDATE deals SET status = $2 WHERE id = $1", deal_id, status)


async def _fetch_deal_row(conn, deal_id: str):
    """Plain dict, not an asyncpg.Record — this connection (opened directly by
    `db_exec`, not through the app's pool) has no jsonb type codec registered
    (see app/db.py::_register_codecs, only applied to the app's own pool), so
    `audit_log` comes back as a raw JSON string here and needs decoding."""
    row = await conn.fetchrow("SELECT * FROM deals WHERE id = $1", deal_id)
    if row is None:
        return None
    data = dict(row)
    if isinstance(data.get("audit_log"), str):
        data["audit_log"] = json.loads(data["audit_log"])
    return data


def test_expire_sweep_marks_expired_and_deletes_files(client, client_as, db_exec):
    deal_id = _create_deal(client_as)["id"]
    db_exec(_backdate_expiry, deal_id, hours=1)

    sf = get_signfinder()
    row_before = db_exec(_fetch_deal_row, deal_id)
    assert sf.storage.exists(row_before["original_pdf_path"])
    assert sf.storage.exists(row_before["initiator_signed_pdf_path"])

    r = client.post("/internal/deals/expire-sweep", headers=_CRON_KEY_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["processed"] >= 1
    assert body["files_deleted"] >= 2

    row = db_exec(_fetch_deal_row, deal_id)
    assert row["status"] == "expired"
    assert row["original_pdf_path"] is None
    assert row["initiator_signed_pdf_path"] is None
    assert row["final_pdf_path"] is None
    assert any(e.get("event") == "expired" for e in row["audit_log"])
    assert not sf.storage.exists(row_before["original_pdf_path"])
    assert not sf.storage.exists(row_before["initiator_signed_pdf_path"])


def test_expire_sweep_signed_deal_keeps_status(client, client_as, db_exec):
    deal_id = _create_deal(client_as)["id"]
    db_exec(_set_status, deal_id, "signed")
    db_exec(_backdate_expiry, deal_id, hours=1)

    r = client.post("/internal/deals/expire-sweep", headers=_CRON_KEY_HEADERS)
    assert r.status_code == 200

    row = db_exec(_fetch_deal_row, deal_id)
    assert row["status"] == "signed"
    assert row["original_pdf_path"] is None
    assert row["initiator_signed_pdf_path"] is None
    assert row["final_pdf_path"] is None
    assert any(e.get("event") == "files_purged" for e in row["audit_log"])


def test_expire_sweep_idempotent(client, client_as, db_exec):
    deal_id = _create_deal(client_as)["id"]
    db_exec(_backdate_expiry, deal_id, hours=1)

    r1 = client.post("/internal/deals/expire-sweep", headers=_CRON_KEY_HEADERS)
    assert r1.status_code == 200
    assert r1.json()["processed"] >= 1

    r2 = client.post("/internal/deals/expire-sweep", headers=_CRON_KEY_HEADERS)
    assert r2.status_code == 200

    row = db_exec(_fetch_deal_row, deal_id)
    assert row["status"] == "expired"
    assert row["original_pdf_path"] is None


def test_purge_old_deletes_row(client, client_as, db_exec):
    deal_id = _create_deal(client_as)["id"]
    db_exec(_backdate_expiry, deal_id, days=31)

    r = client.post("/internal/deals/purge-old", headers=_CRON_KEY_HEADERS)
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1

    row = db_exec(_fetch_deal_row, deal_id)
    assert row is None


def test_internal_endpoints_require_cron_key(client):
    # verify_cron_key defaults a missing header to "" via Header(""), which
    # never equals the real key — deterministically 401, same code path as
    # a present-but-wrong value (no HTTPBearer auto_error ambiguity here).
    r = client.post("/internal/deals/expire-sweep")
    assert r.status_code == 401

    r = client.post("/internal/deals/purge-old")
    assert r.status_code == 401
