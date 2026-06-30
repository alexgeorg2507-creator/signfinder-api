"""Cabinet endpoints: /v1/me/* — all require Firebase JWT.

IB:
- tenant_id (firebase_uid) ONLY from verified JWT, never from body/URL
- Every SQL filters by user_id from token (WHERE user_id = $from_jwt)
- 404 instead of 403 for other-user resources
- extra='forbid' on all Pydantic input models
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.auth import FirebaseToken
from app.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Cabinet"])

_MAX_SIG_UPLOAD = 5 * 1024 * 1024   # 5 MB raw upload
_MAX_SIG_PNG    = 500 * 1024         # 500 KB processed PNG


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


class SignatureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    png_b64: str  # base64 of processed PNG from /process endpoint


class PartyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    role: str = ""


class PartyOut(BaseModel):
    name: str
    role: str


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
    req_raw = row["requisites_json"] or {}
    return ProfileOut(
        full_name=row["full_name"] or "",
        company=row["company"] or "",
        requisites=req_raw.get("text", "") if isinstance(req_raw, dict) else "",
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
              SET full_name       = EXCLUDED.full_name,
                  company         = EXCLUDED.company,
                  requisites_json = EXCLUDED.requisites_json,
                  updated_at      = NOW()
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


# ── signature ─────────────────────────────────────────────────────────────────

@router.post("/me/signature/process")
async def process_signature_ep(
    user: UserDep,
    file: UploadFile = File(...),
) -> Any:
    """OpenCV-process a signature image — preview only, does NOT save."""
    ct = (file.content_type or "").lower()
    if not ct.startswith("image/"):
        raise HTTPException(status_code=422, detail="Только изображения (PNG/JPG/HEIC)")
    raw = await file.read()
    if len(raw) > _MAX_SIG_UPLOAD:
        raise HTTPException(status_code=422, detail="Файл слишком большой (макс 5МБ)")
    try:
        from signfinder.signature import process_signature
        result = process_signature(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Ошибка обработки: {exc}")
    return {
        "processed_png_b64": base64.b64encode(result.png_bytes).decode(),
        "confidence": result.confidence,
        "warnings": result.warnings,
        "output_size": result.output_size,
        "ink_coverage": result.ink_coverage,
    }


@router.get("/me/signature")
async def get_signature(user: UserDep) -> Response:
    """Download current signature as image/png. 404 if not uploaded yet."""
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT png_bytes FROM signatures WHERE user_id = $1 AND png_bytes IS NOT NULL",
            uid,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Подпись не найдена")
    return Response(content=bytes(row["png_bytes"]), media_type="image/png")


@router.put("/me/signature", status_code=204)
async def put_signature(body: SignatureIn, user: UserDep) -> None:
    """Save processed signature (base64 PNG) to DB. One per user, overwrites."""
    uid = user["firebase_uid"]
    try:
        png_bytes = base64.b64decode(body.png_b64)
    except Exception:
        raise HTTPException(status_code=422, detail="Невалидный base64")
    if len(png_bytes) > _MAX_SIG_PNG:
        raise HTTPException(status_code=422, detail="PNG слишком большой (макс 500КБ)")
    if not png_bytes.startswith(b"\x89PNG"):
        raise HTTPException(status_code=422, detail="Ожидается PNG (неверный формат)")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO signatures (user_id, png_bytes, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET png_bytes = EXCLUDED.png_bytes, updated_at = NOW()
            """,
            uid, png_bytes,
        )


# ── party ─────────────────────────────────────────────────────────────────────

@router.get("/me/party", response_model=PartyOut)
async def get_party(user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, role FROM parties WHERE user_id = $1",
            uid,
        )
    if row is None:
        return PartyOut(name="", role="")
    return PartyOut(name=row["name"] or "", role=row["role"] or "")


@router.put("/me/party", response_model=PartyOut)
async def put_party(body: PartyIn, user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO parties (user_id, name, role, patterns_json, updated_at)
            VALUES ($1, $2, $3, '[]'::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET name = EXCLUDED.name, role = EXCLUDED.role, updated_at = NOW()
            """,
            uid, body.name, body.role,
        )
    return PartyOut(name=body.name, role=body.role)
