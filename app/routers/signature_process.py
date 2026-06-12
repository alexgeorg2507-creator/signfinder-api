"""
POST /v1/signers/{signer_id}/signature/process
Обработка подписи — только анализ, ничего не сохраняет.
"""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.dependencies import ApiKeyDep, SignFinderDep
from signfinder.signature import process_signature

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/gif"}


@router.post("/signers/{signer_id}/signature/process")
async def process_signature_preview(
    _: ApiKeyDep,
    sf: SignFinderDep,
    signer_id: str,
    file: UploadFile = File(...),
):
    """
    Предобработка подписи: детекция чернил, обрезка, прозрачный фон.
    НЕ сохраняет. Возвращает RGBA PNG base64 + метрики.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type: {file.content_type}. Allowed: png, jpg, gif",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        result = process_signature(image_bytes)
    except Exception as exc:
        logger.exception("Signature processing failed for signer %s", signer_id)
        raise HTTPException(status_code=422, detail=f"Processing failed: {exc}") from exc

    return {
        "confidence": round(result.confidence, 4),
        "warnings": result.warnings,
        "ink_coverage": round(result.ink_coverage, 4),
        "output_size": list(result.output_size),
        "input_size": list(result.input_size),
        "bbox_original": list(result.bbox_original),
        "processed_png_b64": base64.b64encode(result.png_bytes).decode(),
    }
