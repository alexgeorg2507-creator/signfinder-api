"""Firebase JWT verification middleware for /v1/me/* endpoints."""
from __future__ import annotations

import logging
import os
from typing import Annotated

import firebase_admin
from firebase_admin import auth
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)
# auto_error=False: default HTTPBearer raises 403 on a missing header. We want a
# uniform 401 for every "not authenticated" case (missing header, bad scheme,
# invalid/expired token) — handled explicitly below.
_bearer = HTTPBearer(auto_error=False)


def init_firebase() -> None:
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip() or None
    try:
        firebase_admin.initialize_app(
            options={"projectId": project_id} if project_id else None
        )
        logger.info("Firebase Admin initialized (project=%s)", project_id or "from ADC")
    except ValueError:
        logger.info("Firebase Admin already initialized")


async def _verify_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> dict:
    """Verify Firebase ID token. Returns decoded claims dict."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return auth.verify_id_token(creds.credentials)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# Reusable dependency: decoded Firebase token claims
FirebaseToken = Annotated[dict, Security(_verify_token)]
