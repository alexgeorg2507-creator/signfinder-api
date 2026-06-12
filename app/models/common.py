"""Общие Pydantic-схемы."""
from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


class VersionResponse(BaseModel):
    api_version: str
    signfinder_core_version: str
    environment: str


class HealthResponse(BaseModel):
    status: str
    storage: str | None = None
