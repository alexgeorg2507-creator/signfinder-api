"""Parties CRUD: /v1/parties.

Стороны договора хранятся в storage как parties/{name}.json.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from app.dependencies import ApiKeyDep, SignFinderDep
from app.models.parties import PartyCreate, PartyResponse, PartyUpdate

logger = logging.getLogger(__name__)
router = APIRouter()

_PARTY_KEY = "parties/{name}.json"
_PARTIES_LIST_KEY = "parties/_index.json"


def _read_party(sf, name: str) -> dict | None:
    try:
        raw = sf.storage.read(_PARTY_KEY.format(name=name))
        return json.loads(raw)
    except Exception:
        return None


def _write_party(sf, name: str, data: dict) -> None:
    sf.storage.write(_PARTY_KEY.format(name=name), json.dumps(data).encode())


def _list_parties(sf) -> list[dict]:
    """Читает все party из storage через list + read. Не оптимально, но stateless."""
    try:
        keys = sf.storage.list("parties/")
    except Exception:
        return []
    result = []
    for key in keys:
        if key.endswith(".json") and not key.endswith("_index.json"):
            try:
                raw = sf.storage.read(key)
                result.append(json.loads(raw))
            except Exception:
                pass
    return result


@router.get("/parties", response_model=list[PartyResponse])
async def list_parties(_: ApiKeyDep, sf: SignFinderDep):
    """Список всех сторон договора."""
    return [PartyResponse(**p) for p in _list_parties(sf)]


@router.post("/parties", response_model=PartyResponse, status_code=201)
async def create_party(_: ApiKeyDep, sf: SignFinderDep, body: PartyCreate):
    """Создать новую сторону."""
    if _read_party(sf, body.name):
        raise HTTPException(status_code=409, detail=f"Party '{body.name}' already exists")
    data = body.model_dump()
    try:
        _write_party(sf, body.name, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return PartyResponse(**data)


@router.get("/parties/{name}", response_model=PartyResponse)
async def get_party(_: ApiKeyDep, sf: SignFinderDep, name: str):
    data = _read_party(sf, name)
    if not data:
        raise HTTPException(status_code=404, detail=f"Party '{name}' not found")
    return PartyResponse(**data)


@router.patch("/parties/{name}", response_model=PartyResponse)
async def update_party(_: ApiKeyDep, sf: SignFinderDep, name: str, update: PartyUpdate):
    data = _read_party(sf, name)
    if not data:
        raise HTTPException(status_code=404, detail=f"Party '{name}' not found")
    changes = update.model_dump(exclude_none=True)
    data.update(changes)
    try:
        _write_party(sf, name, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return PartyResponse(**data)


@router.delete("/parties/{name}", status_code=204)
async def delete_party(_: ApiKeyDep, sf: SignFinderDep, name: str):
    if not _read_party(sf, name):
        raise HTTPException(status_code=404, detail=f"Party '{name}' not found")
    try:
        sf.storage.delete(_PARTY_KEY.format(name=name))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
