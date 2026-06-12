"""FastAPI dependencies: SignFinder singleton + API key auth."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
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


# Удобные типы для Depends/Security в роутерах
SignFinderDep = Annotated[SignFinder, Depends(get_signfinder)]
ApiKeyDep = Annotated[str, Security(verify_api_key)]
