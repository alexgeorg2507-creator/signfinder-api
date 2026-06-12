"""Jobs API: статус, список, удаление async jobs."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import ApiKeyDep
from app.job_storage import delete_job, get_job, list_jobs
from app.models.jobs import JobListResponse, JobResponse

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(_: ApiKeyDep, job_id: str):
    """
    Статус async job'а.

    Опрашивается клиентом до status=completed или status=failed.
    result заполнен только при completed.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(**job)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs_endpoint(
    _: ApiKeyDep,
    status: Optional[str] = Query(None, description="Фильтр: pending|running|completed|failed"),
    limit: int = Query(50, ge=1, le=200, description="Максимум записей"),
):
    """Список jobs с опциональным фильтром по статусу."""
    jobs = list_jobs(status=status, limit=limit)
    return JobListResponse(
        jobs=[JobResponse(**j) for j in jobs],
        total=len(jobs),
    )


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job_endpoint(_: ApiKeyDep, job_id: str):
    """Удалить job и связанные временные файлы."""
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
