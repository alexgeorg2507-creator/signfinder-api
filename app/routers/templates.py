"""Templates CRUD: /v1/templates/*.

Используем module-level функции signfinder.templates напрямую
(sf.list_templates() / sf.get_template() на фасаде НЕ существуют).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from app.dependencies import ApiKeyDep, SignFinderDep
from app.models.templates import TemplateListResponse, TemplateResponse, TemplateUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates_endpoint(
    _: ApiKeyDep,
    sf: SignFinderDep,
    language: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
):
    """Список шаблонов с фильтрацией по языку и статусу."""
    from signfinder.templates import list_templates

    try:
        templates = list_templates(sf.storage)
    except Exception as e:
        logger.exception("list_templates failed")
        raise HTTPException(status_code=500, detail=str(e))

    if language:
        templates = [t for t in templates if getattr(t, "language", None) == language]
    if status:
        templates = [t for t in templates if getattr(t, "status", "active") == status]

    return TemplateListResponse.from_list(templates[:limit])


@router.post("/templates", status_code=201)
async def create_template(
    _: ApiKeyDep,
    sf: SignFinderDep,
    payload: dict = Body(...),
):
    """Создать шаблон. Используется в авто-подписании после разбора."""
    from signfinder.templates import DocumentTemplate, save_template

    try:
        tpl = DocumentTemplate(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Невалидный шаблон: {e}")

    try:
        save_template(sf.storage, tpl)
    except Exception as e:
        logger.exception("create_template failed")
        raise HTTPException(status_code=500, detail=str(e))

    return {"id": tpl.template_id, "name": tpl.name}


@router.get("/templates/search")
async def search_templates(
    _: ApiKeyDep,
    sf: SignFinderDep,
    fingerprint: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
):
    """Поиск похожих шаблонов по fingerprint. GET-вариант."""
    from signfinder.templates import list_templates

    try:
        templates = list_templates(sf.storage)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if language:
        templates = [t for t in templates if getattr(t, "language", None) == language]

    return {"results": [TemplateResponse.from_template(t) for t in templates]}


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    _: ApiKeyDep,
    sf: SignFinderDep,
    template_id: str,
):
    """Получить шаблон по ID."""
    from signfinder.templates import load_template

    try:
        tpl = load_template(sf.storage, template_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return TemplateResponse.from_template(tpl)


@router.patch("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    _: ApiKeyDep,
    sf: SignFinderDep,
    template_id: str,
    update: TemplateUpdate,
):
    """Обновить поля шаблона."""
    from signfinder.templates import load_template, save_template

    try:
        tpl = load_template(sf.storage, template_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    changes = update.model_dump(exclude_none=True)
    for key, val in changes.items():
        if hasattr(tpl, key):
            setattr(tpl, key, val)

    try:
        save_template(sf.storage, tpl)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return TemplateResponse.from_template(tpl)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    _: ApiKeyDep,
    sf: SignFinderDep,
    template_id: str,
):
    """Удалить шаблон. 204 если успешно, 404 если не найден."""
    from signfinder.templates import load_template

    try:
        tpl = load_template(sf.storage, template_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    try:
        sf.storage.delete(f"templates/{template_id}.json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


@router.post("/templates/{template_id}/apply")
async def apply_template(
    _: ApiKeyDep,
    sf: SignFinderDep,
    template_id: str,
):
    """
    Применить шаблон к PDF. Принимает file через multipart — TODO в Части 4.

    Сейчас возвращает 501 — метод apply_template не реализован в MVP.
    """
    raise HTTPException(
        status_code=501,
        detail="apply_template not implemented in v1.9. Use /v1/analyze + /v1/sign instead.",
    )
