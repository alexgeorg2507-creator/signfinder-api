"""Роутер /v1/agent/* — тонкие прокси к signfinder-agent:9000."""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import ApiKeyDep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/agent", tags=["Agent"])

_AGENT_URL = os.environ.get("AGENT_URL", "http://agent:9000")
_TIMEOUT = httpx.Timeout(30.0)


def _proxy_get(path: str, **params) -> dict:
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            resp = c.get(f"{_AGENT_URL}{path}",
                         params={k: v for k, v in params.items() if v is not None})
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Agent недоступен")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


def _proxy_post(path: str, body: dict | None = None) -> dict:
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            resp = c.post(f"{_AGENT_URL}{path}", json=body)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Agent недоступен")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


class ResolveRequest(BaseModel):
    uid: str
    action: str
    anchors: list | None = None


@router.get("/status")
def agent_status(_: ApiKeyDep):
    return _proxy_get("/status")


@router.post("/poll-now")
def agent_poll_now(_: ApiKeyDep):
    return _proxy_post("/poll-now")


@router.get("/queue")
def agent_queue(_: ApiKeyDep):
    return _proxy_get("/queue")


@router.get("/queue/{uid}")
def agent_queue_item(_: ApiKeyDep, uid: str):
    return _proxy_get(f"/queue/{uid}")


@router.post("/resolve")
def agent_resolve(_: ApiKeyDep, req: ResolveRequest):
    return _proxy_post("/resolve", {"uid": req.uid, "action": req.action, "anchors": req.anchors})


@router.get("/log")
def agent_log(_: ApiKeyDep, n: int = 50, light: str | None = None):
    return _proxy_get("/log", n=n, light=light)
