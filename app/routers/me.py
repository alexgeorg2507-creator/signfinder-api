"""Cabinet endpoints: /v1/me/* — all require Firebase JWT.

ИБ-чеклист:
- tenant_id (firebase_uid) извлекается ТОЛЬКО из верифицированного JWT, никогда из body/URL
- Все SQL-запросы фильтруются по user_id из токена
- extra='forbid' в Pydantic-моделях — лишние поля реджектятся
- 404 вместо 403 при попытке запросить чужой ресурс
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.auth import FirebaseToken
from app.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Cabinet"])


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_or_create_user(token: FirebaseToken) -> dict:
    """Upsert user on every request — idempotent, O(1) by PK."""
    uid: str = token["uid"]
    email: str = token.get("email", "")
    verified: bool = token.get("email_verified", False)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (firebase_uid, email, email_verified)
            VALUES ($1, $2, $3)
            ON CONFLICT (firebase_uid) DO UPDATE
              SET email = EXCLUDED.email,
                  email_verified = EXCLUDED.email_verified
            RETURNING firebase_uid, email, email_verified, created_at
            """,
            uid, email, verified,
        )
    return dict(row)


UserDep = Annotated[dict, Depends(_get_or_create_user)]


# ── models ────────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = ""
    company: str = ""
    requisites: str = ""


class ProfileOut(BaseModel):
    full_name: str
    company: str
    requisites: str


# ── profile ───────────────────────────────────────────────────────────────────

@router.get("/me/profile", response_model=ProfileOut)
async def get_profile(user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT full_name, company, requisites_json FROM profiles WHERE user_id = $1",
            uid,
        )
    if row is None:
        return ProfileOut(full_name="", company="", requisites="")
    return ProfileOut(
        full_name=row["full_name"] or "",
        company=row["company"] or "",
        requisites=json.dumps(row["requisites_json"] or {}, ensure_ascii=False),
    )


@router.put("/me/profile", response_model=ProfileOut)
async def put_profile(body: ProfileIn, user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO profiles (user_id, full_name, company, requisites_json, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET full_name      = EXCLUDED.full_name,
                  company        = EXCLUDED.company,
                  requisites_json = EXCLUDED.requisites_json,
                  updated_at     = NOW()
            """,
            uid,
            body.full_name,
            body.company,
            json.dumps({"text": body.requisites}, ensure_ascii=False),
        )
    return ProfileOut(
        full_name=body.full_name,
        company=body.company,
        requisites=body.requisites,
    )
