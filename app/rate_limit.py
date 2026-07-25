"""Rate limiting for public endpoints (Deal Cycle E2, THREAT_MODEL_DEAL_CYCLE.md §3.A).

10 req/min per share_token, 60 req/min per IP — SlowAPI. Cloud Run sits
behind a proxy, so the real client IP comes from X-Forwarded-For, not
the direct peer address.
"""
from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_share_token_key(request: Request) -> str:
    return request.path_params.get("share_token", "unknown")


limiter = Limiter(key_func=get_client_ip)
