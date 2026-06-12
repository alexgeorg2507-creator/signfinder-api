
"""
Job storage утилиты для async обработки.

Два backend:
  STORAGE_MODE=local → файлы в {JOBS_STORAGE_PATH}/{job_id}/
  STORAGE_MODE=gcs   → gs://{JOBS_BUCKET}/{job_id}/

Не использует signfinder-core storage — отдельный bucket/папка
специфичная для API job management.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_STORAGE_MODE = os.environ.get("STORAGE_MODE", "local")
_JOBS_STORAGE_PATH = os.environ.get("JOBS_STORAGE_PATH", "./signfinder_jobs")
_JOBS_BUCKET = os.environ.get("JOBS_BUCKET", "signfinder-jobs")

JOB_FILENAME = "job.json"
INPUT_PDF_FILENAME = "input.pdf"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_job(job_type: str, metadata: Optional[dict] = None) -> dict:
    """Создаёт новую Job запись, сохраняет в storage. Возвращает job dict."""
    job_id = str(uuid.uuid4())
    now = _now()
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "metadata": metadata or {},
        "result": None,
        "error": None,
    }
    _save_job(job)
    logger.info("Created job %s type=%s", job_id, job_type)
    return job


def get_job(job_id: str) -> Optional[dict]:
    """Читает Job из storage. None если не найден."""
    try:
        return _load_job(job_id)
    except Exception as e:
        logger.warning("get_job %s failed: %s", job_id, e)
        return None


def update_job_status(
    job_id: str,
    status: str,
    result: Optional[Any] = None,
    error: Optional[str] = None,
) -> dict:
    """Обновляет статус Job, опционально записывает result/error."""
    job = _load_job(job_id)
    if job is None:
        raise KeyError(f"Job {job_id} not found")
    job["status"] = status
    job["updated_at"] = _now()
    if result is not None:
        job["result"] = result
    if error is not None:
        job["error"] = error
    _save_job(job)
    logger.info("Job %s → %s", job_id, status)
    return job


def list_jobs(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Список jobs с необязательным фильтром по статусу."""
    all_jobs = _list_all_jobs()
    if status:
        all_jobs = [j for j in all_jobs if j.get("status") == status]
    all_jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return all_jobs[:limit]


def delete_job(job_id: str) -> bool:
    """Удаляет Job и связанные файлы (PDF input если остался)."""
    try:
        delete_job_input_pdf(job_id)
    except Exception:
        pass
    return _delete_job_record(job_id)


def save_job_input_pdf(job_id: str, pdf_bytes: bytes) -> str:
    """Сохраняет PDF для async обработки. Возвращает storage path."""
    path = _pdf_path(job_id)
    _write_bytes(job_id, INPUT_PDF_FILENAME, pdf_bytes)
    logger.debug("Saved input PDF for job %s (%d bytes)", job_id, len(pdf_bytes))
    return path


def get_job_input_pdf(job_id: str) -> Optional[bytes]:
    """Читает PDF для обработки job'а."""
    return _read_bytes(job_id, INPUT_PDF_FILENAME)


def delete_job_input_pdf(job_id: str) -> None:
    """Удаляет временный PDF после обработки."""
    _delete_file(job_id, INPUT_PDF_FILENAME)
    logger.debug("Deleted input PDF for job %s", job_id)


# ---------------------------------------------------------------------------
# Internal helpers — local backend
# ---------------------------------------------------------------------------


def _job_dir_local(job_id: str) -> str:
    return os.path.join(_JOBS_STORAGE_PATH, job_id)


def _ensure_dir_local(job_id: str) -> str:
    d = _job_dir_local(job_id)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Internal helpers — unified dispatch
# ---------------------------------------------------------------------------


def _save_job(job: dict) -> None:
    job_id = job["job_id"]
    data = json.dumps(job, ensure_ascii=False, indent=2).encode("utf-8")
    _write_bytes(job_id, JOB_FILENAME, data)


def _load_job(job_id: str) -> Optional[dict]:
    data = _read_bytes(job_id, JOB_FILENAME)
    if data is None:
        return None
    return json.loads(data.decode("utf-8"))


def _list_all_jobs() -> list[dict]:
    if _STORAGE_MODE == "gcs":
        return _list_all_jobs_gcs()
    return _list_all_jobs_local()


def _delete_job_record(job_id: str) -> bool:
    return _delete_file(job_id, JOB_FILENAME)


def _pdf_path(job_id: str) -> str:
    if _STORAGE_MODE == "gcs":
        return f"gs://{_JOBS_BUCKET}/{job_id}/{INPUT_PDF_FILENAME}"
    return os.path.join(_job_dir_local(job_id), INPUT_PDF_FILENAME)


# ---------------------------------------------------------------------------
# Low-level read/write
# ---------------------------------------------------------------------------


def _write_bytes(job_id: str, filename: str, data: bytes) -> None:
    if _STORAGE_MODE == "gcs":
        _gcs_write(f"{job_id}/{filename}", data)
    else:
        path = os.path.join(_ensure_dir_local(job_id), filename)
        with open(path, "wb") as f:
            f.write(data)


def _read_bytes(job_id: str, filename: str) -> Optional[bytes]:
    if _STORAGE_MODE == "gcs":
        return _gcs_read(f"{job_id}/{filename}")
    path = os.path.join(_job_dir_local(job_id), filename)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def _delete_file(job_id: str, filename: str) -> bool:
    if _STORAGE_MODE == "gcs":
        return _gcs_delete(f"{job_id}/{filename}")
    path = os.path.join(_job_dir_local(job_id), filename)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ---------------------------------------------------------------------------
# Local backend — list
# ---------------------------------------------------------------------------


def _list_all_jobs_local() -> list[dict]:
    jobs = []
    if not os.path.isdir(_JOBS_STORAGE_PATH):
        return jobs
    for entry in os.scandir(_JOBS_STORAGE_PATH):
        if not entry.is_dir():
            continue
        job_file = os.path.join(entry.path, JOB_FILENAME)
        if not os.path.exists(job_file):
            continue
        try:
            with open(job_file, "rb") as f:
                jobs.append(json.loads(f.read().decode("utf-8")))
        except Exception as e:
            logger.warning("Corrupt job file %s: %s", job_file, e)
    return jobs


# ---------------------------------------------------------------------------
# GCS backend
# ---------------------------------------------------------------------------


def _gcs_client():
    from google.cloud import storage as gcs
    return gcs.Client()


def _gcs_write(blob_name: str, data: bytes) -> None:
    client = _gcs_client()
    bucket = client.bucket(_JOBS_BUCKET)
    bucket.blob(blob_name).upload_from_string(data)


def _gcs_read(blob_name: str) -> Optional[bytes]:
    try:
        client = _gcs_client()
        bucket = client.bucket(_JOBS_BUCKET)
        blob = bucket.blob(blob_name)
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception as e:
        logger.warning("GCS read %s failed: %s", blob_name, e)
        return None


def _gcs_delete(blob_name: str) -> bool:
    try:
        client = _gcs_client()
        bucket = client.bucket(_JOBS_BUCKET)
        blob = bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
            return True
        return False
    except Exception as e:
        logger.warning("GCS delete %s failed: %s", blob_name, e)
        return False


def _list_all_jobs_gcs() -> list[dict]:
    jobs = []
    try:
        client = _gcs_client()
        bucket = client.bucket(_JOBS_BUCKET)
        for blob in bucket.list_blobs(match_glob=f"**/{JOB_FILENAME}"):
            try:
                data = blob.download_as_bytes()
                jobs.append(json.loads(data.decode("utf-8")))
            except Exception as e:
                logger.warning("Corrupt GCS job blob %s: %s", blob.name, e)
    except Exception as e:
        logger.error("GCS list jobs failed: %s", e)
    return jobs


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
