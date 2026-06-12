"""Signers: CRUD профилей подписантов + управление подписью.

Storage layout:
  signers/{id}/profile.json  — профиль (match_markers, aliases, display)
  signers/{id}/signature.png — PNG подписи
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.dependencies import ApiKeyDep, SignFinderDep
from app.models.signers import (
    AliasEntry, SignerProfileCreate, SignerProfileResponse, SignerProfileUpdate,
)
from signfinder.pipeline.settings import (
    list_signer_profiles, load_signer_profile_by_id,
)
from signfinder.signature import process_signature

logger = logging.getLogger(__name__)
router = APIRouter()

_PROFILE_KEY = "signers/{sid}/profile.json"
_SIG_KEY = "signers/{sid}/signature.png"
_SLUG_RE = re.compile(r"^[a-z0-9_\-]{1,40}$")


def _to_response(data: dict, sf) -> SignerProfileResponse:
    """Конвертация raw profile dict → SignerProfileResponse."""
    sid = data.get("id", "")
    has_sig = sf.storage.exists(_SIG_KEY.format(sid=sid))
    return SignerProfileResponse(
        id=sid,
        display=data.get("display", data.get("display_name", "")),
        match_markers=data.get("match_markers", []),
        company_aliases=[AliasEntry(**a) for a in data.get("company_aliases", [])
                         if isinstance(a, dict)],
        signer_aliases=[AliasEntry(**a) for a in data.get("signer_aliases", [])
                        if isinstance(a, dict)],
        has_signature=has_sig,
        updated_at=data.get("updated_at", ""),
    )


def _save_profile(sf, sid: str, data: dict) -> None:
    data["id"] = sid
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sf.storage.write_json(_PROFILE_KEY.format(sid=sid), data)


# ── LIST ──────────────────────────────────────────────────────────────────────

@router.get("/signers", response_model=list[SignerProfileResponse])
async def list_signers(_: ApiKeyDep, sf: SignFinderDep):
    """Список всех профилей подписантов."""
    profiles = list_signer_profiles(sf.storage)
    return [_to_response(p, sf) for p in profiles]


# ── CREATE ────────────────────────────────────────────────────────────────────

@router.post("/signers", response_model=SignerProfileResponse, status_code=201)
async def create_signer(_: ApiKeyDep, sf: SignFinderDep, body: SignerProfileCreate):
    """Создать новый профиль подписанта."""
    if not _SLUG_RE.match(body.id):
        raise HTTPException(status_code=422,
                            detail="id должен быть slug: a-z, 0-9, _ или -, до 40 символов")
    if sf.storage.exists(_PROFILE_KEY.format(sid=body.id)):
        raise HTTPException(status_code=409, detail=f"Профиль '{body.id}' уже существует")

    data = {
        "id": body.id,
        "display": body.display,
        "match_markers": body.match_markers,
        "company_aliases": [a.model_dump() for a in body.company_aliases],
        "signer_aliases": [a.model_dump() for a in body.signer_aliases],
    }
    _save_profile(sf, body.id, data)
    return _to_response(load_signer_profile_by_id(sf.storage, body.id), sf)


# ── GET ───────────────────────────────────────────────────────────────────────

@router.get("/signers/{signer_id}", response_model=SignerProfileResponse)
async def get_signer(_: ApiKeyDep, sf: SignFinderDep, signer_id: str):
    """Профиль подписанта по id."""
    data = load_signer_profile_by_id(sf.storage, signer_id)
    if not data.get("id"):
        raise HTTPException(status_code=404, detail=f"Профиль '{signer_id}' не найден")
    return _to_response(data, sf)


# ── UPDATE ────────────────────────────────────────────────────────────────────

@router.put("/signers/{signer_id}", response_model=SignerProfileResponse)
async def update_signer(
    _: ApiKeyDep, sf: SignFinderDep, signer_id: str, update: SignerProfileUpdate,
):
    """Частичное обновление профиля (только переданные поля)."""
    data = load_signer_profile_by_id(sf.storage, signer_id)
    changes = update.model_dump(exclude_none=True)
    for key in ("company_aliases", "signer_aliases"):
        if key in changes:
            changes[key] = [a.model_dump() if hasattr(a, "model_dump") else a
                            for a in changes[key]]
    data.update(changes)
    _save_profile(sf, signer_id, data)
    return _to_response(load_signer_profile_by_id(sf.storage, signer_id), sf)


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.delete("/signers/{signer_id}", status_code=204)
async def delete_signer(_: ApiKeyDep, sf: SignFinderDep, signer_id: str):
    """Удалить профиль и подпись подписанта. 'default' нельзя удалять."""
    if signer_id == "default":
        raise HTTPException(status_code=403, detail="Профиль 'default' нельзя удалить")
    profile_deleted = sf.storage.delete(_PROFILE_KEY.format(sid=signer_id))
    sf.storage.delete(_SIG_KEY.format(sid=signer_id))
    if not profile_deleted:
        raise HTTPException(status_code=404, detail=f"Профиль '{signer_id}' не найден")


# ── SIGNATURE ─────────────────────────────────────────────────────────────────

@router.get("/signers/{signer_id}/signature")
async def get_signature(_: ApiKeyDep, sf: SignFinderDep, signer_id: str):
    """Скачать PNG подписи."""
    png = sf.storage.read_bytes(_SIG_KEY.format(sid=signer_id))
    if png is None:
        raise HTTPException(status_code=404, detail=f"Подпись '{signer_id}' не найдена")
    return Response(content=png, media_type="image/png",
                    headers={"Content-Disposition":
                             f'attachment; filename="{signer_id}_signature.png"'})


@router.put("/signers/{signer_id}/signature", status_code=204)
async def upload_signature(
    _: ApiKeyDep, sf: SignFinderDep, signer_id: str,
    file: UploadFile = File(..., description="PNG/JPG/GIF файл подписи"),
    auto_process: bool = Query(default=False),
):
    """Загрузить/заменить подпись. auto_process=true → предобработка OpenCV."""
    allowed = {"image/png", "image/jpeg", "image/gif"}
    if not file.content_type or file.content_type.lower() not in allowed:
        raise HTTPException(status_code=422, detail="Только PNG/JPG/GIF")
    raw = await file.read()
    if auto_process:
        try:
            raw = process_signature(raw).png_bytes
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Processing failed: {e}")
    sf.storage.write_bytes(_SIG_KEY.format(sid=signer_id), raw)


@router.post("/signers/{signer_id}/signature/process")
async def process_signature_endpoint(
    _: ApiKeyDep, sf: SignFinderDep, signer_id: str,
    file: UploadFile = File(...),
):
    """Предобработать подпись (OpenCV), НЕ сохранять. Вернуть preview + метрики."""
    raw = await file.read()
    try:
        result = process_signature(raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "processed_png_b64": base64.b64encode(result.png_bytes).decode(),
        "confidence": result.confidence,
        "warnings": result.warnings,
        "output_size": result.output_size,
        "ink_coverage": result.ink_coverage,
    }
