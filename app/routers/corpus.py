"""Corpus: GET/PUT /v1/corpus + файлы документов корпуса.

corpus.json — эталонный корпус для eval-тестов (v1.15).
Хранится в storage как corpus/corpus.json.
Файлы документов (уже сконвертированные в PDF) — corpus/files/<filename>.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.dependencies import ApiKeyDep, SignFinderDep

logger = logging.getLogger(__name__)
router = APIRouter()

_CORPUS_PATH = "corpus/corpus.json"
_CORPUS_FILES_DIR = "corpus/files"
_CORPUS_DEFAULT: dict[str, Any] = {
    "corpus_version": "1.0",
    "created_at": "",
    "description": "",
    "documents": [],
}


def _safe_name(filename: str) -> str:
    """Защита от path traversal: только безопасные символы."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120]


@router.get("/corpus", tags=["Corpus"])
async def get_corpus(_: ApiKeyDep, sf: SignFinderDep) -> dict:
    """Читает corpus.json. Если нет — возвращает пустую структуру."""
    data = sf.storage.read_json(_CORPUS_PATH)
    if data is None:
        return dict(_CORPUS_DEFAULT)
    return data


@router.put("/corpus", tags=["Corpus"])
async def put_corpus(_: ApiKeyDep, sf: SignFinderDep, body: dict) -> dict:
    """Сохраняет corpus.json. body — полный corpus dict."""
    if "documents" not in body:
        raise HTTPException(status_code=422, detail="corpus.json должен содержать поле 'documents'")
    try:
        if not body.get("created_at"):
            body["created_at"] = datetime.now(timezone.utc).isoformat()
        sf.storage.write_json(_CORPUS_PATH, body)
        logger.info("corpus saved: %d documents", len(body.get("documents", [])))
        return body
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/corpus/files/{filename}", tags=["Corpus"])
async def put_corpus_file(
    _: ApiKeyDep, sf: SignFinderDep, filename: str, file: UploadFile = File(...),
) -> dict:
    """Сохраняет файл документа корпуса (PDF-байты) для eval-прогона."""
    data = await file.read()
    path = f"{_CORPUS_FILES_DIR}/{_safe_name(filename)}"
    try:
        sf.storage.write_bytes(path, data)
        logger.info("corpus file saved: %s (%d bytes)", path, len(data))
        return {"status": "saved", "path": path, "size": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/corpus/files/{filename}", tags=["Corpus"])
async def get_corpus_file(_: ApiKeyDep, sf: SignFinderDep, filename: str):
    """Отдаёт ранее сохранённый файл документа корпуса (PDF)."""
    path = f"{_CORPUS_FILES_DIR}/{_safe_name(filename)}"
    data = sf.storage.read_bytes(path)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Файл корпуса не найден: {filename}")
    return Response(content=data, media_type="application/pdf")
