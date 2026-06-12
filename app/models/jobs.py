"""Pydantic модели для async Job API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    job_type: str = "analyze"
    created_at: str
    updated_at: str
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
