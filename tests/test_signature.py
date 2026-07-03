"""CRUD: /v1/me/signature."""
from __future__ import annotations

from tests.conftest import TINY_PNG_B64, USER_A


def test_get_signature_no_upload_404(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me/signature")
    assert r.status_code == 404


def test_put_signature_invalid_base64_422(client_as):
    c = client_as(USER_A)
    r = c.put("/v1/me/signature", json={"png_b64": "a"})
    assert r.status_code == 422


def test_put_signature_valid_png_204(client_as):
    c = client_as(USER_A)
    r = c.put("/v1/me/signature", json={"png_b64": TINY_PNG_B64})
    assert r.status_code == 204


def test_get_signature_after_upload_200_png(client_as):
    c = client_as(USER_A)
    c.put("/v1/me/signature", json={"png_b64": TINY_PNG_B64})

    r = c.get("/v1/me/signature")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
