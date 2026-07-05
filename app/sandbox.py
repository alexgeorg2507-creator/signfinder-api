"""Sandbox-specific guards: rate limit, file size, page count.

Applies only when the request uses SANDBOX_API_KEY.
Rate limit: 3 /v1/analyze calls per IP per calendar day (in-memory, resets on cold start).
File size: 5 MB max.
Page count: 3 pages max.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date

SANDBOX_API_KEY: str = os.environ.get("SANDBOX_API_KEY", "sf-sandbox-2026")

_RATE_LIMIT = 3
_MAX_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB
_MAX_PAGES = 3

# {"YYYY-MM-DD:ip": count}  — resets naturally on new day key
_counters: dict[str, int] = defaultdict(int)


def get_client_ip(request) -> str:
    """Prefer X-Forwarded-For (Cloud Run behind Firebase proxy)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client else "unknown"


def is_sandbox_key(request) -> bool:
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {SANDBOX_API_KEY}"


def check_rate_limit(ip: str) -> None:
    """Increment counter; raise 429 if daily limit exceeded.

    Counter is incremented only once (call this from endpoint handler, not middleware,
    to avoid BaseHTTPMiddleware multi-dispatch for multipart requests).
    """
    from fastapi import HTTPException
    key = f"{date.today().isoformat()}:{ip}"
    _counters[key] += 1
    if _counters[key] > _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Daily sandbox limit reached",
        )


def check_size(pdf_bytes: bytes) -> None:
    """Raise 413 if file exceeds sandbox size limit."""
    from fastapi import HTTPException
    if len(pdf_bytes) > _MAX_SIZE_BYTES:
        mb = len(pdf_bytes) / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({mb:.1f} MB). Sandbox limit is 5 MB.",
        )


def check_page_count(pdf_bytes: bytes) -> None:
    """Raise 422 if PDF has more than 3 pages."""
    from fastapi import HTTPException
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        n = len(doc)
        doc.close()
    except Exception:
        return  # Let the main pipeline handle unreadable PDFs
    if n > _MAX_PAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many pages ({n}). Sandbox limit is {_MAX_PAGES} pages.",
        )
