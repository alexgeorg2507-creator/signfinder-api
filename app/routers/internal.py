"""
Internal endpoints для Cloud Tasks callbacks.

Не требуют API key — защищены X-Internal-Token.
Скрыты из Swagger UI (include_in_schema=False).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException

router = APIRouter()


def verify_internal_token(x_internal_token: str = Header("")) -> None:
    """
    Проверяет X-Internal-Token.

    Если INTERNAL_TOKEN не задан — принимаем любой запрос
    (локальная разработка, CLOUD_TASKS_ENABLED=false).
    """
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if expected and x_internal_token != expected:
        raise HTTPException(status_code=403, detail="Invalid internal token")


@router.post(
    "/internal/process-analyze-job/{job_id}",
    include_in_schema=False,
    status_code=200,
)
async def process_analyze_job_endpoint(
    job_id: str,
    _: None = Depends(verify_internal_token),
):
    """
    Вызывается Cloud Tasks для выполнения async analyze job.

    При CLOUD_TASKS_ENABLED=false этот endpoint не вызывается —
    задача выполняется inline в tasks.py.
    """
    from app.job_processors import process_analyze_job

    process_analyze_job(job_id)
    return {"status": "ok", "job_id": job_id}
