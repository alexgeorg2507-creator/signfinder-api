"""Public signing page: /v1/public/deals/{share_token} (эпик E2, no auth).

signfinder-core's actual PDF overlay (SignFinder.sign) and OpenCV signature
processing (process_signature) aren't exercised end-to-end here — same gap
as /v1/me/sign (see RUNBOOK_TESTING.md "Что НЕ покрыто"). The sign-happy-path
tests monkeypatch both to isolate this router's own logic (anchor
construction, atomic status transition, final PDF storage) rather than
core's PDF manipulation, which has its own test suite in signfinder-core.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import fitz
import pytest

from tests.conftest import TINY_PNG_B64, TINY_PNG_BYTES, USER_A, USER_B

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
    """USER_A creates a deal and marks it sent — the state public endpoints expect."""
    c = client_as(USER_A)
    r = c.post("/v1/deals", json=_deal_payload())
    assert r.status_code == 201
    deal = r.json()
    r = c.post(f"/v1/deals/{deal['id']}/mark-shared", json={"channel": "copy_link"})
    assert r.status_code == 200
    return r.json()


def _valid_pdf_bytes() -> bytes:
    """A real minimal valid PDF — needed wherever fitz has to actually open it
    (e.g. _append_legal_block), unlike the deliberately-fake bytes used for
    original/initiator_signed elsewhere (never opened by this router)."""
    doc = fitz.open()
    doc.new_page()
    out = doc.tobytes()
    doc.close()
    return out


def _patch_sign_pipeline(monkeypatch) -> None:
    """Mock the two signfinder-core calls this router makes directly
    (process_signature, SignFinder.sign) — see module docstring."""
    monkeypatch.setattr(
        "signfinder.signature.process_signature",
        lambda raw: SimpleNamespace(png_bytes=raw, confidence=0.9),
    )
    monkeypatch.setattr(
        "signfinder.SignFinder.sign",
        lambda self, *a, **kw: _valid_pdf_bytes(),
    )


# ── test_deals_public.py (RUNBOOK_TESTING.md, эпик E2) ─────────────────────

def test_get_public_deal_by_token_no_auth(client_as, client):
    deal = _create_sent_deal(client_as)
    r = client.get(f"/v1/public/deals/{deal['share_token']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("sent", "viewed")
    assert "initiator_email" in body


def test_get_public_deal_invalid_token_404(client):
    r = client.get("/v1/public/deals/does-not-exist-token-000000000000")
    assert r.status_code == 404


def test_viewed_status_on_first_get(client_as, client):
    deal = _create_sent_deal(client_as)
    assert deal["status"] == "sent"

    r = client.get(f"/v1/public/deals/{deal['share_token']}")
    assert r.status_code == 200
    assert r.json()["status"] == "viewed"

    # audit_log isn't part of DealPublicView (threat model §3.F) — confirm
    # the transition via the initiator's own private view instead.
    c = client_as(USER_A)
    r2 = c.get(f"/v1/deals/{deal['id']}")
    audit_log = r2.json()["audit_log"]
    viewed_events = [e for e in audit_log if e.get("event") == "viewed"]
    assert len(viewed_events) == 1
    assert "ip" in viewed_events[0] and "ua" in viewed_events[0]


def test_sign_without_consent_checkbox_422(client_as, client):
    deal = _create_sent_deal(client_as)
    r = client.post(
        f"/v1/public/deals/{deal['share_token']}/sign",
        json={"signature_png_b64": TINY_PNG_B64, "consent_pep": False, "signature_source": "file"},
    )
    assert r.status_code == 422


def test_sign_valid_updates_status_and_creates_final_pdf(client_as, client, monkeypatch):
    _patch_sign_pipeline(monkeypatch)
    deal = _create_sent_deal(client_as)

    r = client.post(
        f"/v1/public/deals/{deal['share_token']}/sign",
        json={"signature_png_b64": TINY_PNG_B64, "consent_pep": True, "signature_source": "file"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "signed"

    r = client.get(f"/v1/public/deals/{deal['share_token']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "signed"
    assert body["has_final_pdf"] is True

    r = client.get(f"/v1/public/deals/{deal['share_token']}/final-pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_final_pdf_legal_block_has_initiator_ip_ua(client_as, client, monkeypatch):
    """E7, DEAL_CYCLE_SPEC.md §7/§9 criterion 8 — legal-trail text actually
    contains the initiator's own ip, not just the counterparty's (real text
    extraction via fitz, not just "PDF is valid").

    Uses a distinct X-Forwarded-For for the initiator's create-deal request
    so its ip differs from the counterparty's (TestClient's default
    "testclient" for both actors would otherwise make the two identical and
    the assertion meaningless). Doesn't assert on the Cyrillic label text
    itself — _append_legal_block falls back to the Latin-only "helv" font
    when the Liberation Sans TTF isn't on PATH (see _LEGAL_BLOCK_FONTFILE),
    which is true on a bare CI runner/local Windows box vs the Docker image,
    so Cyrillic would render as "?" there through no fault of the ip/ua fix.
    """
    _patch_sign_pipeline(monkeypatch)
    c = client_as(USER_A)
    r = c.post("/v1/deals", json=_deal_payload(), headers={"X-Forwarded-For": "203.0.113.5"})
    assert r.status_code == 201
    deal = r.json()
    created_event = next(e for e in deal["audit_log"] if e["event"] == "created")
    assert created_event["ip"] == "203.0.113.5"

    r = c.post(f"/v1/deals/{deal['id']}/mark-shared", json={"channel": "copy_link"})
    assert r.status_code == 200
    deal = r.json()

    r = client.post(
        f"/v1/public/deals/{deal['share_token']}/sign",
        json={"signature_png_b64": TINY_PNG_B64, "consent_pep": True, "signature_source": "file"},
    )
    assert r.status_code == 200

    r = client.get(f"/v1/public/deals/{deal['share_token']}/final-pdf")
    assert r.status_code == 200

    doc = fitz.open(stream=r.content, filetype="pdf")
    try:
        full_text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    assert "203.0.113.5" in full_text


# ── threat model §6 (test_deals_public.py, per TASK_deal_cycle_E2.md §2.7) ──

def test_public_view_no_sensitive_fields(client_as, client):
    deal = _create_sent_deal(client_as)
    r = client.get(f"/v1/public/deals/{deal['share_token']}")
    assert r.status_code == 200
    body = r.json()
    forbidden = (
        "initiator_tenant_id", "initiator_firebase_uid", "id",
        "original_pdf_path", "initiator_signed_pdf_path", "final_pdf_path",
        "audit_log", "share_token",
    )
    for field in forbidden:
        assert field not in body, f"{field} leaked in public view"


def test_sign_race_condition_409(client_as, client, monkeypatch):
    _patch_sign_pipeline(monkeypatch)
    deal = _create_sent_deal(client_as)
    payload = {"signature_png_b64": TINY_PNG_B64, "consent_pep": True, "signature_source": "file"}

    r1 = client.post(f"/v1/public/deals/{deal['share_token']}/sign", json=payload)
    assert r1.status_code == 200

    r2 = client.post(f"/v1/public/deals/{deal['share_token']}/sign", json=payload)
    assert r2.status_code == 409


def test_sign_extra_fields_422(client_as, client):
    deal = _create_sent_deal(client_as)
    payload = {
        "signature_png_b64": TINY_PNG_B64, "consent_pep": True, "signature_source": "file",
        "deal_id": deal["id"], "tenant_id": "evil-uid",
    }
    r = client.post(f"/v1/public/deals/{deal['share_token']}/sign", json=payload)
    assert r.status_code == 422


# ── signature preview (no auth, needed since the internal
#    /v1/signers/{id}/signature/process is ApiKeyDep-protected and a public
#    anonymous page can't hold that secret) ──────────────────────────────────

def test_signature_preview_no_auth(client_as, client):
    deal = _create_sent_deal(client_as)
    r = client.post(
        f"/v1/public/deals/{deal['share_token']}/signature/preview",
        files={"file": ("sig.png", TINY_PNG_BYTES, "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "processed_png_b64" in body
    assert "confidence" in body


def test_signature_preview_invalid_token_404(client):
    r = client.post(
        "/v1/public/deals/does-not-exist-token-000000000000/signature/preview",
        files={"file": ("sig.png", TINY_PNG_BYTES, "image/png")},
    )
    assert r.status_code == 404
