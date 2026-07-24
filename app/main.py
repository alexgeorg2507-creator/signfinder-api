"""SignFinder FastAPI application."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import audit, internal, jobs, parties, pipeline, settings, signers, system, templates
from app.routers import llm_config, signature_process, corpus, agent, me, deals

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_API_PREFIX = "/api"

# Dockerfile copies only app/ (no `pip install .` of this distribution), so
# package metadata isn't registered in the production image — fall back to a
# literal kept in sync with pyproject.toml's [project].version.
_FALLBACK_API_VERSION = "1.19.0"
try:
    _API_VERSION = _pkg_version("signfinder-api")
except PackageNotFoundError:
    _API_VERSION = _FALLBACK_API_VERSION


def _init_llm_config() -> None:
    """Write LLM config from DEEPSEEK_API_KEY env var BEFORE SignFinder init."""
    import json
    import os

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not deepseek_key:
        return
    try:
        from signfinder.llm.config import _config_path, load_config
        cfg_path = _config_path()
        cfg = load_config()
        if not cfg.get("providers", {}).get("deepseek", {}).get("api_key"):
            cfg["active_provider"] = "deepseek"
            cfg["providers"]["deepseek"]["api_key"] = deepseek_key
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            logger.info("LLM config initialized from DEEPSEEK_API_KEY")
    except Exception as e:
        logger.warning("Could not write LLM config: %s", e)


def _seed_sandbox_storage(sf) -> None:
    """Seed signer profile, signature, and sign_mode into storage (idempotent)."""
    import json
    from pathlib import Path

    resources = Path(__file__).parent / "resources"
    seeds = [
        ("signers/default/profile.json",  resources / "default_profile.json",  "json"),
        ("signers/default/signature.png", resources / "default_signature.png", "bytes"),
        ("settings/sign_mode.json",       None,                                "json"),
    ]
    sign_mode_default = {"use_signature": True, "use_marker": False, "marker_color": "pink"}

    for storage_key, src, kind in seeds:
        try:
            if sf.storage.exists(storage_key):
                continue
            if kind == "json":
                data = sign_mode_default if src is None else json.loads(src.read_text(encoding="utf-8"))
                sf.storage.write_json(storage_key, data)
            else:
                sf.storage.write_bytes(storage_key, src.read_bytes())
            logger.info("Sandbox default written: %s", storage_key)
        except Exception as e:
            logger.warning("Could not seed %s: %s", storage_key, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    build_number = os.environ.get("BUILD_NUMBER", "")
    build_sha = os.environ.get("BUILD_SHA", "")
    logger.info(
        "SignFinder API v%s (build #%s, sha: %s) starting up...",
        _API_VERSION, build_number or "?", build_sha or "?",
    )
    _init_llm_config()  # must run before get_signfinder() reads llm_config.json

    from app.auth import init_firebase
    from app.db import init_db, close_db
    init_firebase()
    await init_db()

    from app.dependencies import get_signfinder
    import signfinder

    try:
        sf = get_signfinder()
        logger.info(
            "SignFinder Core v%s loaded. Storage: %s. LLM: %s",
            signfinder.__version__,
            type(sf.storage).__name__,
            sf.llm.provider_name,
        )
        _seed_sandbox_storage(sf)
    except Exception as e:
        logger.error("Failed to initialize SignFinder: %s", e)
        raise

    yield

    logger.info("SignFinder API shutting down...")
    from app.db import close_db
    await close_db()


app = FastAPI(
    title="SignFinder API",
    description="REST API for automatic signature placement in contracts",
    version=_API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.middleware("http")
async def strip_api_prefix(request, call_next):
    """Strip /api prefix added by Firebase Hosting rewrite."""
    path = request.scope.get("path", "")
    if path.startswith(_API_PREFIX + "/"):
        request.scope["path"] = path[len(_API_PREFIX):]
        request.scope["raw_path"] = request.scope["path"].encode()
    elif path == _API_PREFIX:
        request.scope["path"] = "/"
        request.scope["raw_path"] = b"/"
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(pipeline.router, prefix="/v1", tags=["Pipeline"])
app.include_router(templates.router, prefix="/v1", tags=["Templates"])
app.include_router(signers.router, prefix="/v1", tags=["Signers"])
app.include_router(parties.router, prefix="/v1", tags=["Parties"])
app.include_router(settings.router, prefix="/v1", tags=["Settings"])
app.include_router(audit.router, prefix="/v1", tags=["Audit"])
app.include_router(jobs.router, prefix="/v1", tags=["Jobs"])
app.include_router(llm_config.router)
app.include_router(signature_process.router, prefix="/v1", tags=["Signature"])
app.include_router(corpus.router, prefix="/v1", tags=["Corpus"])
app.include_router(agent.router)
app.include_router(internal.router, tags=["Internal"])
app.include_router(me.router, prefix="/v1", tags=["Cabinet"])
app.include_router(deals.router, prefix="/v1")
