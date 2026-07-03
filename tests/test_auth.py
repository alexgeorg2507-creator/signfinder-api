"""ИБ: auth bypass, token validation on /v1/me/*.

Exercises the real Firebase verification path (not the dependency_overrides
shortcut used elsewhere) — patches firebase_admin.auth.verify_id_token so no
network call to Google is made.
"""
from __future__ import annotations

from tests.conftest import USER_A


def test_no_auth_header_401(client):
    r = client.get("/v1/me/profile")
    assert r.status_code == 401


def test_invalid_token_401(client, monkeypatch):
    from app import auth as auth_module

    def _raise(_token: str):
        raise ValueError("invalid signature")

    monkeypatch.setattr(auth_module.auth, "verify_id_token", _raise)

    r = client.get(
        "/v1/me/profile", headers={"Authorization": "Bearer garbage-token"}
    )
    assert r.status_code == 401


def test_valid_token_200(client, monkeypatch):
    from app import auth as auth_module

    def _fake_verify(token: str):
        assert token == "good-token"
        return {"uid": USER_A, "email": "alice@test.local", "email_verified": True}

    monkeypatch.setattr(auth_module.auth, "verify_id_token", _fake_verify)

    r = client.get(
        "/v1/me/profile", headers={"Authorization": "Bearer good-token"}
    )
    assert r.status_code == 200
