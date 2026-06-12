"""Audit log: GET /v1/audit.

В v1.9 — читает audit events из storage: audit/*.json.
Фильтрация по from/to — на уровне API (не storage-level query).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import ApiKeyDep, SignFinderDep

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/audit")
async def get_audit(
    _: ApiKeyDep,
    sf: SignFinderDep,
    from_date: Optional[str] = Query(None, alias="from", description="ISO date: 2024-01-01"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO date: 2024-12-31"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Журнал решений SignFinder."""
    try:
        keys = sf.storage.list("audit/")
    except Exception:
        return {"events": [], "total": 0}

    events = []
    for key in sorted(keys, reverse=True):
        if not key.endswith(".json"):
            continue
        try:
            raw = sf.storage.read(key)
            event = json.loads(raw)
            events.append(event)
        except Exception:
            pass

    # Фильтрация по дате
    if from_date:
        try:
            dt_from = datetime.fromisoformat(from_date)
            events = [e for e in events if datetime.fromisoformat(e.get("ts", "1970-01-01")) >= dt_from]
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid from date: {from_date}")

    if to_date:
        try:
            dt_to = datetime.fromisoformat(to_date)
            events = [e for e in events if datetime.fromisoformat(e.get("ts", "9999-01-01")) <= dt_to]
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid to date: {to_date}")

    return {"events": events[:limit], "total": len(events)}
