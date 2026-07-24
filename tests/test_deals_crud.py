"""CRUD: /v1/deals (SignfinderLand v2.0.0 Deal Cycle, эпик E1).

Deal rows aren't covered by conftest's autouse `_cleanup_test_users` (it only
knows about users/profiles/parties/signatures/usage_counters), and `deals`
has a FK to `users(firebase_uid)` with no ON DELETE CASCADE — so a leftover
deal row would make `_cleanup_test_users`'s own teardown fail with a foreign
key violation for every other test in the suite. `_cleanup_test_deals` below
deletes deals rows first; pytest tears down function-scoped autouse fixtures
in reverse of setup order, and conftest fixtures are set up before same-scope
fixtures declared in the test module, so this file's teardown runs before
conftest's `_cleanup_test_users` teardown.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta

import pytest

from tests.conftest import USER_A, USER_B

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
    for uid in (USER_A, USER_B):
        await conn.execute("DELETE FROM deals WHERE initiator_tenant_id=$1", uid)


@pytest.fixture(autouse=True)
def _cleanup_test_deals(db_exec):
    db_exec(_delete_test_deals)
    yield
    db_exec(_delete_test_deals)


def test_create_deal_from_signed_pdf(client_as):
    c = client_as(USER_A)
    r = c.post("/v1/deals", json=_deal_payload())
    assert r.status_code == 201
    body = r.json()

    assert len(body["share_token"]) == 32
    assert body["status"] == "draft"

    created_at = _parse_dt(body["created_at"])
    expires_at = _parse_dt(body["expires_at"])
    assert abs((expires_at - created_at) - timedelta(days=7)) < timedelta(seconds=5)


def test_list_deals_own_only(client_as):
    a = client_as(USER_A)
    r = a.post("/v1/deals", json=_deal_payload())
    assert r.status_code == 201

    b = client_as(USER_B)
    r = b.get("/v1/deals")
    assert r.status_code == 200
    assert r.json() == []


def test_get_deal_details_own_only(client_as):
    a = client_as(USER_A)
    r = a.post("/v1/deals", json=_deal_payload())
    deal_id = r.json()["id"]

    b = client_as(USER_B)
    r = b.get(f"/v1/deals/{deal_id}")
    assert r.status_code == 404


def test_mark_shared_updates_status(client_as):
    c = client_as(USER_A)
    r = c.post("/v1/deals", json=_deal_payload())
    deal_id = r.json()["id"]

    r = c.post(f"/v1/deals/{deal_id}/mark-shared", json={"channel": "whatsapp"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"
    assert body["share_channel_used"] == "whatsapp"

    r = c.get(f"/v1/deals/{deal_id}")
    audit_log = r.json()["audit_log"]
    assert any(e.get("event") == "sent" for e in audit_log)


def test_deal_create_extra_fields_422(client_as):
    c = client_as(USER_A)
    payload = _deal_payload()
    payload["initiator_tenant_id"] = "evil-uid"
    r = c.post("/v1/deals", json=payload)
    assert r.status_code == 422


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)
