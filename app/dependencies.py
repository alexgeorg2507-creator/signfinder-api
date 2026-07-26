"""FastAPI dependencies: SignFinder singleton + API key auth."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from signfinder import SignFinder

bearer_scheme = HTTPBearer()


@lru_cache(maxsize=1)
def get_signfinder() -> SignFinder:
    """Синглтон SignFinder. Инициализируется один раз, живёт весь процесс."""
    return SignFinder()  # читает env vars через Config.from_env()


def verify_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
) -> str:
    """
    Проверяет Authorization: Bearer <key> против API_KEY env var.

    v1.9 — один статичный ключ.
    v2.x — расширяется до multi-tenant через tenant_id в ключе.
    """
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY env var is not set")

    if credentials.credentials != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def verify_cron_key(x_deals_cron_key: str = Header("")) -> str:
    """
    Проверяет X-Deals-Cron-Key против того же API_KEY env var — другое имя
    заголовка, тот же секрет.

    Только для /internal/deals/expire-sweep и /internal/deals/purge-old
    (Cloud Scheduler HTTP target). Не Authorization: Bearer, потому что
    Cloud Scheduler резервирует имя заголовка "Authorization" под свой
    собственный oauth_token/oidc_token oneof в HttpTarget (подтверждено
    Google Cloud API reference, HttpTarget.headers field description,
    2026-07-26) — значение, переданное через --headers с этим именем,
    молча обнуляется, если ни oauth_token, ни oidc_token не заданы.
    См. TASK_e5_scheduler_auth_followup.md. Остальные ApiKeyDep-эндпоинты
    (signature_process и т.д.) не затронуты — они не вызываются Cloud
    Scheduler, им это ограничение не мешает.
    """
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY env var is not set")

    if x_deals_cron_key != api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid cron key")
    return x_deals_cron_key


# Удобные типы для Depends/Security в роутерах
SignFinderDep = Annotated[SignFinder, Depends(get_signfinder)]
ApiKeyDep = Annotated[str, Security(verify_api_key)]
CronKeyDep = Annotated[str, Depends(verify_cron_key)]
