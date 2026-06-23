"""Pydantic-схемы для /v1/analyze.

Маппинг реальных полей AnalysisResult (signfinder-core):
    traffic_light       → traffic_light
    matcher_result      → matched_template (MatcherResult)
    applied_template    → applied_template_id (DocumentTemplate.id)
    anchors             → anchors (list[TextAnchor])
    matches             → matches (list[SignMatch])
    our_side            → our_side
    error               → error
    pipeline_debug      → pipeline_debug
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class AnchorResponse(BaseModel):
    id: str
    anchor_level: int
    anchor_text: str
    position: str
    generated_pattern: str
    bbox: list[float]  # [x0, y0, x1, y1]
    added_by: str
    page_hint: str


class SignMatchResponse(BaseModel):
    id: str
    page: int
    bbox: list[float]
    context: str
    party: str
    pattern: str
    confidence: float


class MatcherResultResponse(BaseModel):
    traffic_light: str
    best_match_template_id: Optional[str] = None
    best_match_score: Optional[float] = None
    candidates_count: int = 0


class ReviewFindingResponse(BaseModel):
    axis: str
    severity: str          # critical | warning | info
    note: str
    clause: Optional[str] = None


class ReviewResponse(BaseModel):
    traffic_light: str                      # green | yellow | red
    summary: str = ""
    findings: list[ReviewFindingResponse] = []
    error: Optional[str] = None
    truncated: bool = False


class AnalysisResponse(BaseModel):
    traffic_light: Literal["green", "yellow", "no_match"]
    anchors: list[AnchorResponse]
    matches: list[SignMatchResponse]
    matched_template: Optional[MatcherResultResponse]
    applied_template_id: Optional[str]
    our_side: Optional[dict[str, Any]]
    error: Optional[str]
    pipeline_debug: dict[str, Any]
    fingerprint: Optional[dict[str, Any]] = None
    detected_signer_id: Optional[str] = None
    review: Optional[ReviewResponse] = None

    @staticmethod
    def _review_from_dict(rev: Optional[dict]) -> Optional["ReviewResponse"]:
        if not rev:
            return None
        findings = [
            ReviewFindingResponse(
                axis=f.get("axis", "other"),
                severity=f.get("severity", "info"),
                note=f.get("note", ""),
                clause=f.get("clause"),
            )
            for f in rev.get("findings", [])
        ]
        return ReviewResponse(
            traffic_light=rev.get("traffic_light", "yellow"),
            summary=rev.get("summary", ""),
            findings=findings,
            error=rev.get("error"),
            truncated=rev.get("truncated", False),
        )

    @classmethod
    def from_result(cls, result) -> "AnalysisResponse":
        """Конвертирует AnalysisResult из signfinder-core."""
        # TextAnchor → AnchorResponse
        anchors = []
        for a in (result.anchors or []):
            try:
                anchors.append(AnchorResponse(**{
                    k: getattr(a, k)
                    for k in ("id", "anchor_level", "anchor_text", "position",
                               "generated_pattern", "bbox", "added_by", "page_hint")
                    if hasattr(a, k)
                }))
            except Exception:
                pass

        # SignMatch → SignMatchResponse
        matches = []
        for m in (result.matches or []):
            try:
                matches.append(SignMatchResponse(**{
                    k: getattr(m, k)
                    for k in ("id", "page", "bbox", "context", "party", "pattern", "confidence")
                    if hasattr(m, k)
                }))
            except Exception:
                pass

        # MatcherResult
        matcher_resp = None
        mr = result.matcher_result
        if mr is not None:
            best_id = None
            best_score = None
            if hasattr(mr, "best_match") and mr.best_match:
                best_id = getattr(mr.best_match, "template_id", None)
                best_score = getattr(mr.best_match, "score", None)
            candidates = len(getattr(mr, "candidates", []))
            matcher_resp = MatcherResultResponse(
                traffic_light=getattr(mr, "traffic_light", "no_match"),
                best_match_template_id=best_id,
                best_match_score=best_score,
                candidates_count=candidates,
            )

        applied_id = None
        at = result.applied_template
        if at is not None:
            applied_id = getattr(at, "id", None)

        return cls(
            traffic_light=result.traffic_light,
            anchors=anchors,
            matches=matches,
            matched_template=matcher_resp,
            applied_template_id=applied_id,
            our_side=result.our_side,
            error=result.error,
            pipeline_debug=result.pipeline_debug or {},
            fingerprint=getattr(result, "fingerprint", None),
            detected_signer_id=getattr(result, "detected_signer_id", None),
            review=cls._review_from_dict(getattr(result, "review", None)),
        )


# ── Batch (v1.12) ─────────────────────────────────────────────────────────────

class BatchItemResponse(BaseModel):
    """Один результат в пакетном анализе."""
    filename: str
    elapsed_ms: int
    analysis: Optional[AnalysisResponse] = None
    error: Optional[str] = None  # заполняется если файл упал целиком


class BatchAnalysisResponse(BaseModel):
    """Ответ POST /v1/analyze/batch."""
    total: int
    succeeded: int
    failed: int
    items: list[BatchItemResponse]
