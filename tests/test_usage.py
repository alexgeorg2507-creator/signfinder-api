"""Лимиты: /v1/me/usage счётчик, 429 при превышении на /v1/me/analyze."""
from __future__ import annotations

from datetime import datetime, timezone

from tests.conftest import USER_A


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def test_get_usage_new_user(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me/usage")
    assert r.status_code == 200
    assert r.json() == {"doc_count": 0, "limit": 10, "period": _current_period()}


def test_analyze_429_when_at_limit(client_as, db_exec):
    c = client_as(USER_A)
    # touch /v1/me/usage first so the users row exists (FK for usage_counters)
    c.get("/v1/me/usage")
    period = _current_period()

    db_exec(
        lambda conn: conn.execute(
            "INSERT INTO usage_counters (user_id, period, doc_count) VALUES ($1, $2, 10) "
            "ON CONFLICT (user_id, period) DO UPDATE SET doc_count = 10",
            USER_A, period,
        )
    )

    files = {"file": ("test.pdf", b"%PDF-fake", "application/pdf")}
    r = c.post("/v1/me/analyze", files=files)
    assert r.status_code == 429

    count = db_exec(
        lambda conn: conn.fetchval(
            "SELECT doc_count FROM usage_counters WHERE user_id=$1 AND period=$2",
            USER_A, period,
        )
    )
    assert count == 10
