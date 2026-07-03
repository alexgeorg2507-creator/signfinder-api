"""ИБ: IDOR between two users — every /v1/me/* resource must be strictly
scoped to the caller's own firebase_uid (from the verified JWT), never
leaking another user's data via GET or overwriting it via PUT.
"""
from __future__ import annotations

from tests.conftest import TINY_PNG_B64, USER_A, USER_B


def test_profile_idor(client_as):
    a = client_as(USER_A)
    r = a.put(
        "/v1/me/profile",
        json={"full_name": "Alice Alison", "company": "Acme", "requisites": "INN 123"},
    )
    assert r.status_code == 200

    b = client_as(USER_B)
    r = b.get("/v1/me/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == ""
    assert body["company"] == ""
    assert body["requisites"] == ""


def test_signature_idor(client_as):
    a = client_as(USER_A)
    r = a.put("/v1/me/signature", json={"png_b64": TINY_PNG_B64})
    assert r.status_code == 204

    b = client_as(USER_B)
    r = b.get("/v1/me/signature")
    assert r.status_code == 404
