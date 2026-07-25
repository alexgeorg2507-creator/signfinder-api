"""Rate limits on /v1/public/deals/* (THREAT_MODEL_DEAL_CYCLE.md §3.A, эпик E2).

`limiter.reset()` at the start of each test — SlowAPI's default in-memory
storage is process-wide and the `client` fixture is session-scoped, so
without resetting, counts would leak across every other test in the suite
that happens to hit a public endpoint (all keyed on the same TestClient
"IP"), making these tests order-dependent.
"""
from __future__ import annotations

import base64

import pytest

from app.rate_limit import limiter
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


def _create_sent_deal(client_as) -> dict:
    c = client_as(USER_A)
    r = c.post("/v1/deals", json=_deal_payload())
    deal = r.json()
    r = c.post(f"/v1/deals/{deal['id']}/mark-shared", json={"channel": "copy_link"})
    return r.json()


def test_share_token_ratelimit_10_per_min(client_as, client):
    limiter.reset()
    deal = _create_sent_deal(client_as)

    statuses = [
        client.get(f"/v1/public/deals/{deal['share_token']}").status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429


def test_ip_ratelimit_60_per_min(client_as, client):
    limiter.reset()
    # 61 distinct deals (distinct share_tokens) so only the per-IP limiter
    # (not the per-token one, 10/min) can be what trips at request 61.
    tokens = [_create_sent_deal(client_as)["share_token"] for _ in range(61)]

    statuses = [client.get(f"/v1/public/deals/{t}").status_code for t in tokens]
    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429
