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
_bearer = HTTPBearer()


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
    creds: Annotated[HTTPAuthorizationCredentials, Security(_bearer)],
) -> dict:
    """Verify Firebase ID token. Returns decoded claims dict."""
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
