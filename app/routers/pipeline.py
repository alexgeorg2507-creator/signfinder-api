"""Pipeline endpoints: analyze, sign, anchor/from-click, preview.

v1.9 Part 3: async режим к /analyze (?async=true).
v1.12.0: /analyze/batch
FIX v1.12.1: storage.read() → storage.read_bytes()
FIX v1.13.1: signature_scale пробрасывается в sf.sign()
v1.14.0: /sign читает sign_mode из storage, передаёт use_signature/use_marker/marker_color
"""
from __future__ import annotations

import json
import logging
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.dependencies import ApiKeyDep, SignFinderDep
from app.models.analysis import AnalysisResponse, BatchAnalysisResponse, BatchItemResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_SIGN_MODE_DEFAULT = {"use_signature": True, "use_marker": False, "marker_color": "pink"}


@router.post("/analyze")
async def analyze_document(
    _: ApiKeyDep,
    sf: SignFinderDep,
    file: UploadFile = File(..., description="PDF файл договора"),
    language: str | None = Form(None, description="Язык: ru, en, pl. None = автодетект"),
    async_mode: bool = Form(False, alias="async", description="true = async, вернёт job_id"),
):
    """Полный анализ документа: матчинг шаблонов + поиск мест подписи."""
    if async_mode:
        from app.job_storage import create_job, save_job_input_pdf
        from app.tasks import enqueue_job
        pdf_bytes = await file.read()
        job = create_job("analyze", metadata={"language": language, "filename": file.filename or "document.pdf"})
        job_id = job["job_id"]
        save_job_input_pdf(job_id, pdf_bytes)
        enqueue_job(job_id, f"/v1/internal/process-analyze-job/{job_id}")
        return {"job_id": job_id, "status": "pending", "poll_url": f"/v1/jobs/{job_id}"}

    pdf_bytes = await file.read()
    try:
        result = sf.analyze(pdf_bytes, language=language, filename=file.filename or "document.pdf")
    except Exception as e:
        logger.warning("analyze failed (broken/unreadable PDF): %s", e)
        return AnalysisResponse(
            traffic_light="no_match",
            anchors=[],
            matches=[],
            matched_template=None,
            applied_template_id=None,
            our_side=None,
            error=str(e),
            pipeline_debug={},
        )
    return AnalysisResponse.from_result(result)


@router.post("/analyze/batch")
async def analyze_batch(
    _: ApiKeyDep,
    sf: SignFinderDep,
    files: list[UploadFile] = File(..., description="Список PDF файлов (до 100)"),
    language: str | None = Form(None, description="Язык для всех файлов. None = автодетект"),
) -> BatchAnalysisResponse:
    """Пакетный анализ. Ошибка одного файла не роняет батч. Лимит 100."""
    import time
    if len(files) > 100:
        raise HTTPException(status_code=413, detail="Максимум 100 файлов на запрос")
    items: list[BatchItemResponse] = []
    succeeded = 0
    failed = 0
    for f in files:
        fname = f.filename or "document.pdf"
        t0 = time.monotonic()
        try:
            pdf_bytes = await f.read()
            result = sf.analyze(pdf_bytes, language=language, filename=fname)
            elapsed = int((time.monotonic() - t0) * 1000)
            analysis = AnalysisResponse.from_result(result)
            items.append(BatchItemResponse(filename=fname, elapsed_ms=elapsed, analysis=analysis, error=None))
            failed += 1 if result.traffic_light == "no_match" else 0
            succeeded += 0 if result.traffic_light == "no_match" else 1
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.exception("batch item failed: %s", fname)
            items.append(BatchItemResponse(filename=fname, elapsed_ms=elapsed, analysis=None, error=str(e)))
            failed += 1
    return BatchAnalysisResponse(total=len(files), succeeded=succeeded, failed=failed, items=items)


@router.post("/sign")
async def sign_document(
    _: ApiKeyDep,
    sf: SignFinderDep,
    file: UploadFile = File(..., description="PDF файл для подписания"),
    anchors_json: str = Form(..., description="JSON список якорей [{id, bbox, page_hint, ...}]"),
    signer_id: str = Form("default", description="ID подписанта (PNG из storage)"),
    signature_scale: float = Form(1.0, description="Масштаб подписи (1.0 = 42pt = 15мм высота)"),
):
    """Наложить подпись/маркер по якорям. Режим задаётся через /settings/sign-mode."""
    pdf_bytes = await file.read()

    try:
        anchors = json.loads(anchors_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="anchors_json: невалидный JSON")

    raw_mode = sf.storage.read_json("settings/sign_mode.json")
    sign_mode = raw_mode if raw_mode is not None else _SIGN_MODE_DEFAULT
    use_signature = sign_mode.get("use_signature", True)
    use_marker = sign_mode.get("use_marker", False)
    marker_color = sign_mode.get("marker_color", "pink")

    png_bytes = None
    if use_signature:
        sig_key = f"signers/{signer_id}/signature.png"
        png_bytes = sf.storage.read_bytes(sig_key)
        if png_bytes is None:
            raise HTTPException(status_code=404, detail=f"Подпись для '{signer_id}' не найдена ({sig_key})")

    from datetime import datetime, timezone

    from signfinder.anchors import TextAnchor
    anchor_objects = []
    for a in anchors:
        try:
            bbox = a.get("bbox", [0, 0, 100, 20])
            anchor_objects.append(TextAnchor(
                id=a.get("id", "a0"),
                anchor_type=a.get("anchor_type", "text_proximity"),
                anchor_level=a.get("anchor_level", 1),
                anchor_text=a.get("anchor_text", ""),
                position=a.get("position", "below"),
                offset_pt=a.get("offset_pt", 0.0),
                generated_pattern=a.get("generated_pattern", ""),
                context_before=a.get("context_before", ""),
                context_after=a.get("context_after", ""),
                page_hint=str(a.get("page_hint", "0")),
                added_by=a.get("added_by", "manual_click"),
                added_at=a.get("added_at", datetime.now(timezone.utc).isoformat()),
                bbox=tuple(bbox),
            ))
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Невалидный якорь {a}: {e}")

    try:
        signed_bytes = sf.sign(
            pdf_bytes, anchor_objects, png_bytes,
            scale=signature_scale,
            use_signature=use_signature,
            use_marker=use_marker,
            marker_color=marker_color,
        )
    except Exception as e:
        logger.exception("sign failed")
        raise HTTPException(status_code=422, detail=str(e))

    raw_name = f"signed_{file.filename or 'document.pdf'}"
    ascii_name = raw_name.encode("ascii", "replace").decode("ascii")
    utf8_name = quote(raw_name)
    return Response(
        content=signed_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{utf8_name}"
            )
        },
    )


@router.post("/anchor/from-click")
async def build_anchor_from_click(
    _: ApiKeyDep,
    sf: SignFinderDep,
    file: UploadFile = File(..., description="PDF файл"),
    page: int = Form(..., description="Номер страницы (0-based)"),
    x: float = Form(..., description="X координата клика в points"),
    y: float = Form(..., description="Y координата клика в points"),
    language: str = Form("ru", description="Язык документа"),
):
    """Строит TextAnchor по клику оператора."""
    pdf_bytes = await file.read()
    try:
        anchor = sf.build_anchor_from_click(pdf_bytes, page, x, y, language)
    except Exception as e:
        logger.exception("build_anchor_from_click failed")
        raise HTTPException(status_code=422, detail=str(e))
    if anchor is None:
        raise HTTPException(status_code=422, detail="Нет текста рядом с кликом.")
    return anchor.__dict__


@router.post("/preview")
async def preview_page(
    _: ApiKeyDep,
    sf: SignFinderDep,
    file: UploadFile = File(..., description="PDF файл"),
    page: int = Form(0, description="Номер страницы (0-based)"),
    scale: float = Form(2.0, description="Масштаб (2.0 = 144 DPI)"),
):
    """Рендер страницы PDF → PNG."""
    pdf_bytes = await file.read()
    try:
        from signfinder.pdf import render_page_with_highlights
        png_bytes = render_page_with_highlights(pdf_bytes, page_num=page, highlights=[], scale=scale)
    except Exception as e:
        logger.exception("preview failed")
        raise HTTPException(status_code=422, detail=str(e))
    return Response(content=png_bytes, media_type="image/png")
