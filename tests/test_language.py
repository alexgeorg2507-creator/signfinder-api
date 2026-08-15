"""TASK_i18n_en.md §1 — users.language / deals.language: set-once-on-insert
via X-UI-Language, never touched on later upserts, explicit PUT to change,
copied once into deals at create_deal time."""
from __future__ import annotations

import base64

import pytest

from tests.conftest import USER_A

# deals has a FK to users(firebase_uid) with no ON DELETE CASCADE - a
# leftover deal row from test_create_deal_copies_initiator_language would
# make conftest's own _cleanup_test_users teardown fail with a foreign key
# violation for every other test in the suite (same reasoning as
# test_deals_crud.py's own docstring).
async def _delete_test_deals(conn) -> None:
    await conn.execute("DELETE FROM deals WHERE initiator_tenant_id=$1", USER_A)


@pytest.fixture(autouse=True)
def _cleanup_test_deals(db_exec):
    db_exec(_delete_test_deals)
    yield
    db_exec(_delete_test_deals)

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


def test_new_user_language_from_header(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me", headers={"X-UI-Language": "en"})
    assert r.status_code == 200
    assert r.json()["language"] == "en"


def test_new_user_no_header_defaults_ru(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me")
    assert r.status_code == 200
    assert r.json()["language"] == "ru"


def test_new_user_invalid_header_value_defaults_ru(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me", headers={"X-UI-Language": "de"})
    assert r.status_code == 200
    assert r.json()["language"] == "ru"


def test_later_visit_does_not_overwrite_language(client_as):
    """The exact bug the task warns about: a returning 'en' user hitting
    plain /app (no header, or a stray 'ru' header) must not get silently
    reset."""
    c = client_as(USER_A)
    r = c.get("/v1/me", headers={"X-UI-Language": "en"})
    assert r.json()["language"] == "en"

    r = c.get("/v1/me")  # later visit, no header at all
    assert r.status_code == 200
    assert r.json()["language"] == "en"

    r = c.get("/v1/me", headers={"X-UI-Language": "ru"})  # even with an explicit 'ru'
    assert r.status_code == 200
    assert r.json()["language"] == "en"


def test_put_language_switches_it(client_as):
    c = client_as(USER_A)
    c.get("/v1/me")  # ensures the row exists as 'ru'

    r = c.put("/v1/me/language", json={"language": "en"})
    assert r.status_code == 204

    r = c.get("/v1/me")
    assert r.json()["language"] == "en"


def test_put_language_invalid_value_422(client_as):
    c = client_as(USER_A)
    r = c.put("/v1/me/language", json={"language": "de"})
    assert r.status_code == 422


def test_put_language_requires_auth(client):
    r = client.put("/v1/me/language", json={"language": "en"})
    assert r.status_code == 401


def test_create_deal_copies_initiator_language(client_as, db_exec):
    c = client_as(USER_A)
    c.get("/v1/me", headers={"X-UI-Language": "en"})  # sets users.language='en'

    r = c.post("/v1/deals", json=_deal_payload())
    assert r.status_code == 201
    deal_id = r.json()["id"]

    lang = db_exec(
        lambda conn: conn.fetchval(
            "SELECT language FROM deals WHERE id=$1", deal_id
        )
    )
    assert lang == "en"
