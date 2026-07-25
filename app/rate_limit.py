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


# key_style="endpoint" (default is "url"): our public routes have
# share_token IN the URL path itself (/v1/public/deals/{share_token}), so
# the default url-based scope would fragment the per-IP limiter into one
# independent bucket per token — defeating it entirely, since every request
# in practice hits a different token. Scoping by endpoint (function name,
# constant across tokens) keeps each Limit's own key_func as the only thing
# that varies, which is what actually distinguishes per-token vs per-IP.
# Confirmed empirically: with the default url style, 61 requests across 61
# distinct tokens from the "same IP" never tripped the 60/minute limit at
# all (each token got its own untouched bucket).
limiter = Limiter(key_func=get_client_ip, key_style="endpoint")
