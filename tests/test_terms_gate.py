"""TASK_fix21.md — blocking terms-acceptance gate: GET /v1/me,
POST /v1/me/accept-terms, terms_acceptance_log journal on users."""
from __future__ import annotations

import json

from tests.conftest import USER_A


def test_get_me_new_user_terms_not_accepted(client_as):
    c = client_as(USER_A)
    r = c.get("/v1/me")
    assert r.status_code == 200
    assert r.json() == {"email_verified": True, "terms_accepted": False}


def test_accept_terms_then_get_me_shows_accepted(client_as):
    c = client_as(USER_A)
    r = c.post("/v1/me/accept-terms")
    assert r.status_code == 204

    r = c.get("/v1/me")
    assert r.status_code == 200
    assert r.json()["terms_accepted"] is True


def test_accept_terms_records_ip_ua_in_log(client_as, db_exec):
    """DoD: verify the real DB row, not just trust the code — same rigor as
    the E7 legal-trail ip/ua check."""
    c = client_as(USER_A)
    r = c.post("/v1/me/accept-terms")
    assert r.status_code == 204

    raw = db_exec(
        lambda conn: conn.fetchval(
            "SELECT terms_acceptance_log FROM users WHERE firebase_uid=$1", USER_A
        )
    )
    log = json.loads(raw) if isinstance(raw, str) else raw
    assert len(log) == 1
    entry = log[0]
    assert entry["ip"]
    assert entry["ua"]
    assert entry["version"]
    assert entry["accepted_at"]


def test_accept_terms_appends_not_overwrites(client_as, db_exec):
    c = client_as(USER_A)
    c.post("/v1/me/accept-terms")
    c.post("/v1/me/accept-terms")

    raw = db_exec(
        lambda conn: conn.fetchval(
            "SELECT terms_acceptance_log FROM users WHERE firebase_uid=$1", USER_A
        )
    )
    log = json.loads(raw) if isinstance(raw, str) else raw
    assert len(log) == 2


def test_stale_version_in_log_requires_reaccept(client_as, db_exec):
    """Gate condition is 'last entry's version == CURRENT_TERMS_VERSION', not
    'log is non-empty' — an old acceptance under a since-changed version must
    still trigger the gate."""
    c = client_as(USER_A)
    c.post("/v1/me/accept-terms")  # ensures the users row exists

    stale_entry = json.dumps([{
        "version": "2020-01-01", "accepted_at": "2020-01-01T00:00:00+00:00",
        "ip": "1.2.3.4", "ua": "old-browser",
    }])
    db_exec(
        lambda conn: conn.execute(
            "UPDATE users SET terms_acceptance_log = $1::jsonb WHERE firebase_uid=$2",
            stale_entry, USER_A,
        )
    )

    r = c.get("/v1/me")
    assert r.status_code == 200
    assert r.json()["terms_accepted"] is False


def test_accept_terms_requires_auth(client):
    r = client.post("/v1/me/accept-terms")
    assert r.status_code == 401


def test_get_me_requires_auth(client):
    r = client.get("/v1/me")
    assert r.status_code == 401
