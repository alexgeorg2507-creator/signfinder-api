"""Shared fixtures for the /v1/me/* (Cabinet) test suite.

Runs against the real `signfinder-cab-test` Cloud SQL DB via Cloud SQL Auth
Proxy (TCP, see app/db.py DATABASE_URL support). Two fixed test users
(USER_A / USER_B) are used throughout; their rows are wiped before and after
every test so the shared test DB is left clean.
"""
from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote

import asyncpg
import pytest
from fastapi.testclient import TestClient

TEST_PROJECT = "signfinder-cab-test"
TEST_INSTANCE = f"{TEST_PROJECT}:europe-west1:signfinder-db"

USER_A = "test-uid-alice"
USER_B = "test-uid-bob"

# Smallest possible valid PNG (1x1, transparent) — used by test_signature.py / test_idor.py.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
TINY_PNG_BYTES = base64.b64decode(TINY_PNG_B64)


def _fetch_db_password() -> str:
    gcloud = shutil.which("gcloud")
    if not gcloud:
        raise RuntimeError("gcloud CLI not found on PATH")
    # gcloud's bundled Python crashes on Windows (UnicodeEncodeError: 'charmap')
    # writing non-ASCII output when stdout isn't a real console (i.e. piped, as
    # subprocess does here) unless forced to UTF-8.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(
        [
            gcloud, "secrets", "versions", "access", "latest",
            "--secret=db-password", f"--project={TEST_PROJECT}",
        ],
        capture_output=True, text=True, encoding="utf-8", check=True, env=env,
    )
    # gcloud on Windows prefixes stdout with a UTF-8 BOM that str.strip() does
    # not remove.
    return result.stdout.strip().lstrip("﻿")


def _find_cloud_sql_proxy() -> str:
    exe = shutil.which("cloud-sql-proxy") or shutil.which("cloud-sql-proxy.exe")
    if not exe:
        raise RuntimeError(
            "cloud-sql-proxy not found on PATH — install the Cloud SQL Auth "
            "Proxy (part of google-cloud-sdk) to run this suite."
        )
    return exe


@pytest.fixture(scope="session", autouse=True)
def _test_environment():
    """Start Cloud SQL Auth Proxy and set env vars BEFORE the app starts.

    Must run before the `client` fixture creates TestClient(app), because
    entering TestClient's context triggers app.main.lifespan() -> init_db().
    """
    tmp_storage = tempfile.mkdtemp(prefix="signfinder-test-")
    os.environ["STORAGE_MODE"] = "local"
    os.environ["STORAGE_PATH"] = tmp_storage
    os.environ["API_KEY"] = "test_key_123"
    os.environ.setdefault("DEEPSEEK_API_KEY", "")
    os.environ["FIREBASE_PROJECT_ID"] = TEST_PROJECT

    password = _fetch_db_password()
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://signfinder:{quote(password, safe='')}@127.0.0.1:5432/signfinder"
    )

    proxy_path = _find_cloud_sql_proxy()
    proxy = subprocess.Popen(
        [proxy_path, TEST_INSTANCE, "--port=5432"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(5)
    if proxy.poll() is not None:
        raise RuntimeError(
            "cloud-sql-proxy exited early — check `gcloud auth "
            "application-default login` and access to signfinder-cab-test."
        )

    yield

    proxy.terminate()
    try:
        proxy.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proxy.kill()
    shutil.rmtree(tmp_storage, ignore_errors=True)


@pytest.fixture(scope="session")
def client(_test_environment):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _asyncpg_dsn() -> str:
    # TestClient's ASGI lifespan runs the app's own asyncpg pool on an internal
    # anyio portal event loop — a *different* loop than the one pytest-asyncio
    # (or plain asyncio.run) uses for test/fixture code. Reusing that pool from
    # here would raise "Future attached to a different loop". Instead every
    # test-side DB call opens its own short-lived connection via asyncio.run().
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture
def db_exec(_test_environment):
    """Run a one-off async DB call against the test DB on an isolated
    connection/event loop. Usage: db_exec(lambda conn: conn.fetchval(...))."""

    def _exec(fn, *args, **kwargs):
        async def _runner():
            conn = await asyncpg.connect(dsn=_asyncpg_dsn())
            try:
                return await fn(conn, *args, **kwargs)
            finally:
                await conn.close()

        return asyncio.run(_runner())

    return _exec


async def _delete_test_rows(conn: asyncpg.Connection) -> None:
    for uid in (USER_A, USER_B):
        await conn.execute("DELETE FROM usage_counters WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM signatures WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM parties WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM profiles WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM users WHERE firebase_uid=$1", uid)


@pytest.fixture(autouse=True)
def _cleanup_test_users(db_exec):
    db_exec(_delete_test_rows)
    yield
    db_exec(_delete_test_rows)


@pytest.fixture
def client_as(client):
    """Override Firebase auth to act as the given uid — no real token needed."""
    from app.auth import _verify_token
    from app.main import app

    def _as(uid: str) -> TestClient:
        app.dependency_overrides[_verify_token] = lambda: {
            "uid": uid,
            "email": f"{uid}@test.local",
            "email_verified": True,
        }
        return client

    yield _as
    app.dependency_overrides.pop(_verify_token, None)
