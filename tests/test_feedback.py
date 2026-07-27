"""POST /v1/feedback — Deal Cycle E6. Mocks httpx.AsyncClient.post, never
calls the real Telegram API."""
from __future__ import annotations

import logging

import pytest

from tests.conftest import USER_A

_PAYLOAD = {
    "feature_request": "Массовая отправка нескольким контрагентам сразу",
    "source": "LinkedIn",
    "would_refer": True,
    "contact": "alice@example.com",
}


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def _patch_telegram(monkeypatch, *, status_code: int = 200, calls: list | None = None):
    async def _fake_post(self, url, json=None, **kwargs):
        if calls is not None:
            calls.append({"url": url, "json": json})
        return _FakeResponse(status_code, "" if status_code == 200 else "Internal Server Error")
    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)


def test_feedback_sends_to_telegram_mocked(client_as, monkeypatch):
    monkeypatch.setenv("TG_FEEDBACK_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TG_FEEDBACK_CHAT_ID", "12345")
    calls: list = []
    _patch_telegram(monkeypatch, calls=calls)

    r = client_as(USER_A).post("/v1/feedback", json=_PAYLOAD)
    assert r.status_code == 200

    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.telegram.org/bottest-bot-token/sendMessage"
    assert calls[0]["json"]["chat_id"] == "12345"
    text = calls[0]["json"]["text"]
    assert _PAYLOAD["feature_request"] in text
    assert "LinkedIn" in text
    assert "да" in text
    assert "alice@example.com" in text


def test_feedback_requires_auth(client):
    r = client.post("/v1/feedback", json=_PAYLOAD)
    assert r.status_code == 401


def test_feedback_extra_fields_422(client_as):
    payload = dict(_PAYLOAD)
    payload["evil_field"] = "x"
    r = client_as(USER_A).post("/v1/feedback", json=payload)
    assert r.status_code == 422


def test_feedback_telegram_down_still_returns_200(client_as, monkeypatch, caplog):
    monkeypatch.setenv("TG_FEEDBACK_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TG_FEEDBACK_CHAT_ID", "12345")
    _patch_telegram(monkeypatch, status_code=500)

    with caplog.at_level(logging.ERROR, logger="app.routers.feedback"):
        r = client_as(USER_A).post("/v1/feedback", json=_PAYLOAD)

    assert r.status_code == 200
    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)


def test_feedback_strips_secret_whitespace(client_as, monkeypatch):
    """Regression: a secret provisioned via `"value" | gcloud secrets create
    ... --data-file=-` in PowerShell picks up a trailing CRLF from the pipe.
    Observed live on signfinder-cab-test: httpx.InvalidURL on a bare '\\r'
    right after the token in the request URL."""
    monkeypatch.setenv("TG_FEEDBACK_BOT_TOKEN", "test-bot-token\r\n")
    monkeypatch.setenv("TG_FEEDBACK_CHAT_ID", "12345\r\n")
    calls: list = []
    _patch_telegram(monkeypatch, calls=calls)

    r = client_as(USER_A).post("/v1/feedback", json=_PAYLOAD)
    assert r.status_code == 200

    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.telegram.org/bottest-bot-token/sendMessage"
    assert calls[0]["json"]["chat_id"] == "12345"
