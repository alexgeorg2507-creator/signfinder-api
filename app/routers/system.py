"""System endpoints: /healthz, /readyz, /health, /v1/version."""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz", tags=["System"])
@router.get("/health", tags=["System"])
async def liveness(request: Request):
    """Cloud Run liveness probe + Streamlit health check."""
    try:
        import signfinder
        core_version = signfinder.__version__
    except Exception:
        core_version = "unknown"
    return {
        "status": "ok",
        "api_version": request.app.version,
        "api_build": os.environ.get("BUILD_NUMBER", ""),
        "core_version": core_version,
    }


@router.get("/readyz", tags=["System"])
async def readiness():
    """Cloud Run readiness probe."""
    try:
        from app.dependencies import get_signfinder
        sf = get_signfinder()
        return {"status": "ok", "storage": type(sf.storage).__name__}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(e)},
        )


@router.get("/v1/version", tags=["System"])
async def version(request: Request):
    """Версии API и core-пакета. api_version берётся из FastAPI app.version (main.py)."""
    try:
        import signfinder
        core_version = signfinder.__version__
    except Exception:
        core_version = "unknown"

    return {
        "api_version": request.app.version,
        "api_build": os.environ.get("BUILD_NUMBER", ""),
        "api_sha": os.environ.get("BUILD_SHA", ""),
        "signfinder_core_version": core_version,
        "environment": os.environ.get("ENVIRONMENT", "development"),
    }
