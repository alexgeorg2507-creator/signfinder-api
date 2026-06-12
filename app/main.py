"""SignFinder FastAPI application — v1.18.3."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import audit, internal, jobs, parties, pipeline, settings, signers, system, templates
from app.routers import llm_config, signature_process, corpus, agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SignFinder API starting up...")
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
    except Exception as e:
        logger.error("Failed to initialize SignFinder: %s", e)
        raise

    yield

    logger.info("SignFinder API shutting down...")


app = FastAPI(
    title="SignFinder API",
    description="REST API for automatic signature placement in contracts",
    version="1.18.3",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

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
