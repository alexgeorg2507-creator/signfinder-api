"""Pydantic-схемы для /v1/templates."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class TemplateResponse(BaseModel):
    id: str
    name: str
    language: str
    status: str
    anchor_count: int
    usage_count: int
    signature_scale: float = 1.0
    extra: dict[str, Any] = {}

    @classmethod
    def from_template(cls, tpl) -> "TemplateResponse":
        # template_id — реальный атрибут DocumentTemplate; "id" — legacy fallback
        tid = getattr(tpl, "template_id", None) or getattr(tpl, "id", "")
        anchors = getattr(tpl, "anchors", []) or []
        usage_stats = getattr(tpl, "usage_stats", {}) or {}
        fp = getattr(tpl, "fingerprint", {}) or {}
        return cls(
            id=tid,
            name=getattr(tpl, "name", ""),
            language=getattr(tpl, "language", "ru"),
            status=getattr(tpl, "status", "active"),
            anchor_count=len(anchors),
            usage_count=usage_stats.get("times_applied", 0),
            signature_scale=float(getattr(tpl, "signature_scale", 1.0) or 1.0),
            extra={
                "created_at": getattr(tpl, "created_at", ""),
                "created_by": getattr(tpl, "created_by", ""),
                "anchors": anchors[:10],
                "fingerprint_simhash": fp.get("simhash", ""),
                "fingerprint_words": fp.get("top_words", [])[:15],
                "times_confirmed": usage_stats.get("times_confirmed", 0),
                "times_rejected": usage_stats.get("times_rejected", 0),
                "last_used": usage_stats.get("last_used"),
            },
        )


class TemplateListResponse(BaseModel):
    templates: list[TemplateResponse]
    total: int = 0
    cursor: Optional[str] = None

    @classmethod
    def from_list(cls, templates) -> "TemplateListResponse":
        items = [TemplateResponse.from_template(t) for t in templates]
        return cls(templates=items, total=len(items))


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    language: Optional[str] = None
