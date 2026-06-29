"""Async Postgres pool via Cloud SQL Auth Proxy unix socket (Cloud Run standard)."""
from __future__ import annotations

import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_db() -> None:
    global _pool

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
