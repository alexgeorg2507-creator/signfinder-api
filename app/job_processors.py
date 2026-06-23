"""
Обработчики async jobs.

Вызываются либо через Cloud Tasks callback (/v1/internal/process-analyze-job/{id}),
либо синхронно при CLOUD_TASKS_ENABLED=false.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from app.dependencies import get_signfinder
from app.job_storage import (
    delete_job_input_pdf,
    get_job,
    get_job_input_pdf,
    update_job_status,
)

logger = logging.getLogger(__name__)


def process_analyze_job(job_id: str) -> None:
    """
    Обрабатывает async analyze job.

    Читает PDF из временного storage → запускает sf.analyze() →
    сохраняет result → удаляет временный PDF.
    """
    job = get_job(job_id)
    if not job:
        logger.error("process_analyze_job: job %s not found", job_id)
        return

    logger.info("Starting analyze job %s", job_id)
    update_job_status(job_id, "running")

    try:
        pdf_bytes = get_job_input_pdf(job_id)
        if not pdf_bytes:
            raise ValueError(f"Input PDF not found for job {job_id}")

        sf = get_signfinder()
        meta = job.get("metadata") or {}
        language = meta.get("language")
        filename = meta.get("filename", "document.pdf")
        with_review = meta.get("with_review", False)

        result = sf.analyze(pdf_bytes, language=language, filename=filename, with_review=with_review)
        result_dict = _serialize_result(result)

        update_job_status(job_id, "completed", result=result_dict)
        logger.info("Job %s completed", job_id)

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        update_job_status(job_id, "failed", error=str(e))

    finally:
        try:
            delete_job_input_pdf(job_id)
        except Exception as cleanup_err:
            logger.warning("Failed to delete input PDF for job %s: %s", job_id, cleanup_err)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_result(result) -> dict:
    """Конвертирует AnalysisResult (dataclass или Pydantic) в JSON-safe dict."""
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    try:
        return asdict(result)
    except Exception:
        pass
    return _deep_serialize(result.__dict__)


def _deep_serialize(obj):
    """Рекурсивно конвертирует вложенные объекты в примитивы."""
    if isinstance(obj, dict):
        return {k: _deep_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_deep_serialize(i) for i in obj]
    if hasattr(obj, "__dict__"):
        return _deep_serialize(obj.__dict__)
    return obj
