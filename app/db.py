"""Async Postgres pool via Cloud SQL Auth Proxy unix socket (Cloud Run standard)."""
from __future__ import annotations

import json
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Auto-decode/encode json/jsonb columns as dict/list — asyncpg returns them
    as raw text otherwise (bit profiles.requisites_json, parties.patterns_json)."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def init_db() -> None:
    global _pool

    # TCP path (Alembic, pytest, or any non-Cloud-Run runner) — e.g. via Cloud SQL
    # Auth Proxy on 127.0.0.1. Cloud Run never sets this; unix-socket path below is
    # unaffected.
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        # Accept the SQLAlchemy-style DSN used by Alembic too (postgresql+asyncpg://)
        # — asyncpg itself only understands the plain postgresql:// scheme.
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        _pool = await asyncpg.create_pool(
            dsn=dsn, min_size=1, max_size=5, init=_init_connection
        )
        logger.info("DB pool ready via DATABASE_URL (TCP)")
        return

    cloud_sql_instance = os.environ.get("CLOUD_SQL_INSTANCE", "").strip()
    db_user = os.environ.get("DB_USER", "signfinder")
    db_name = os.environ.get("DB_NAME", "signfinder")
    db_pass = os.environ.get("DB_PASSWORD", "")

    if not cloud_sql_instance:
        logger.warning("CLOUD_SQL_INSTANCE not set — DB disabled")
        return

    # Cloud Run mounts the Cloud SQL proxy at /cloudsql/<instance>
    socket_dir = f"/cloudsql/{cloud_sql_instance}"

    _pool = await asyncpg.create_pool(
        user=db_user,
        password=db_pass,
        database=db_name,
        host=socket_dir,
        min_size=1,
        max_size=5,
        init=_init_connection,
    )
    logger.info("DB pool ready: %s / %s", cloud_sql_instance, db_name)


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB not initialized — check CLOUD_SQL_INSTANCE env var")
    return _pool
