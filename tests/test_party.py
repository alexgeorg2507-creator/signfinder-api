"""CRUD: /v1/me/party."""
from __future__ import annotations

from tests.conftest import USER_A


def test_get_party_new_user_empty(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me/party")
    assert r.status_code == 200
    assert r.json() == {"name": "", "role": ""}


def test_put_party_valid_200(client_as):
    c = client_as(USER_A)
    payload = {"name": "ООО Ромашка", "role": "Заказчик"}
    r = c.put("/v1/me/party", json=payload)
    assert r.status_code == 200
    assert r.json() == payload

    r2 = c.get("/v1/me/party")
    assert r2.json() == payload


def test_put_party_extra_fields_422(client_as):
    c = client_as(USER_A)
    r = c.put("/v1/me/party", json={"name": "X", "role": "Y", "unexpected": True})
    assert r.status_code == 422
