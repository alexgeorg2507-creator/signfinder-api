"""
Cloud Tasks клиент с fallback для локальной разработки.

CLOUD_TASKS_ENABLED=false (default) → задача выполняется синхронно
                                       в том же процессе. GCP не нужен.
CLOUD_TASKS_ENABLED=true            → HTTP task в GCP Cloud Tasks очередь.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def enqueue_job(job_id: str, endpoint: str) -> bool:
    """
    Ставит задачу в очередь.

    endpoint — путь вида /v1/internal/process-analyze-job/{job_id}
    Возвращает True если задача принята (или выполнена локально).
    """
    if os.environ.get("CLOUD_TASKS_ENABLED", "false").lower() != "true":
        logger.info("CLOUD_TASKS_ENABLED=false, executing job %s inline", job_id)
        _execute_job_locally(job_id, endpoint)
        return True

    return _enqueue_gcp(job_id, endpoint)


# ---------------------------------------------------------------------------
# GCP Cloud Tasks
# ---------------------------------------------------------------------------


def _enqueue_gcp(job_id: str, endpoint: str) -> bool:
    try:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        project = os.environ["GCP_PROJECT"]
        location = os.environ.get("CLOUD_TASKS_LOCATION", "europe-west1")
        queue = os.environ.get("CLOUD_TASKS_QUEUE", "signfinder-jobs")

        parent = client.queue_path(project, location, queue)
        api_url = os.environ["API_INTERNAL_URL"].rstrip("/")

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{api_url}{endpoint}",
                "headers": {
                    "Content-Type": "application/json",
                    "X-Internal-Token": os.environ.get("INTERNAL_TOKEN", ""),
                },
                "body": json.dumps({"job_id": job_id}).encode(),
            }
        }

        response = client.create_task(request={"parent": parent, "task": task})
        logger.info("Enqueued Cloud Tasks task %s for job %s", response.name, job_id)
        return True

    except Exception as e:
        logger.error("Failed to enqueue job %s via Cloud Tasks: %s", job_id, e)
        return False


# ---------------------------------------------------------------------------
# Local fallback
# ---------------------------------------------------------------------------


def _execute_job_locally(job_id: str, endpoint: str) -> None:
    """Локальный режим: выполняем обработку синхронно в том же процессе."""
    from app.job_processors import process_analyze_job

    if "/process-analyze-job/" in endpoint:
        process_analyze_job(job_id)
    else:
        logger.warning("Unknown endpoint for local execution: %s", endpoint)
