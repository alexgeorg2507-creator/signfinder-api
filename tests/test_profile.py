"""CRUD: /v1/me/profile."""
from __future__ import annotations

from tests.conftest import USER_A


def test_get_profile_new_user_empty(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me/profile")
    assert r.status_code == 200
    assert r.json() == {"full_name": "", "company": "", "requisites": ""}


def test_put_profile_valid_persists(client_as):
    c = client_as(USER_A)
    payload = {"full_name": "Alice Alison", "company": "Acme LLC", "requisites": "INN 7701234567"}
    r = c.put("/v1/me/profile", json=payload)
    assert r.status_code == 200
    assert r.json() == payload

    r2 = c.get("/v1/me/profile")
    assert r2.json() == payload


def test_put_profile_extra_fields_422(client_as):
    c = client_as(USER_A)
    r = c.put(
        "/v1/me/profile",
        json={"full_name": "Alice", "company": "", "requisites": "", "is_admin": True},
    )
    assert r.status_code == 422


def test_put_profile_sql_injection_stored_as_text(client_as, db_exec):
    c = client_as(USER_A)
    payload = "Robert'); DROP TABLE users;--"
    r = c.put("/v1/me/profile", json={"full_name": payload, "company": "", "requisites": ""})
    assert r.status_code == 200
    assert r.json()["full_name"] == payload

    r2 = c.get("/v1/me/profile")
    assert r2.json()["full_name"] == payload

    # sanity: table not dropped, injection was never executed as SQL
    count = db_exec(lambda conn: conn.fetchval("SELECT count(*) FROM users"))
    assert count is not None
