"""Cabinet endpoints: /v1/me/* — all require Firebase JWT.

IB:
- tenant_id (firebase_uid) ONLY from verified JWT, never from body/URL
- Every SQL filters by user_id from token (WHERE user_id = $from_jwt)
- 404 instead of 403 for other-user resources
- extra='forbid' on all Pydantic input models
- M3: documents processed in-memory only, never persisted;
  prompt-injection isolation is in sf.analyze() (signfinder-core)
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.auth import FirebaseToken
from app.db import get_pool
from app.dependencies import SignFinderDep
from app.models.analysis import AnalysisResponse
from app.tenant_storage import TenantScopedStorage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Cabinet"])

_MAX_SIG_UPLOAD = 5 * 1024 * 1024   # 5 MB raw upload
_MAX_SIG_PNG    = 500 * 1024         # 500 KB processed PNG
_MAX_DOC_SIZE   = 5 * 1024 * 1024   # 5 MB cabinet doc limit
_MAX_DOC_PAGES  = 10  # было 3
_MONTHLY_LIMIT  = 100

_ALLOWED_DOC_EXTENSIONS = {"pdf", "doc", "docx"}
_ALLOWED_DOC_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_or_create_user(token: FirebaseToken) -> dict:
    """Upsert user on every request — idempotent, O(1) by PK."""
    uid: str = token["uid"]
    email: str = token.get("email", "")
    verified: bool = token.get("email_verified", False)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (firebase_uid, email, email_verified)
            VALUES ($1, $2, $3)
            ON CONFLICT (firebase_uid) DO UPDATE
              SET email = EXCLUDED.email,
                  email_verified = EXCLUDED.email_verified
            RETURNING firebase_uid, email, email_verified, created_at
            """,
            uid, email, verified,
        )
    return dict(row)


UserDep = Annotated[dict, Depends(_get_or_create_user)]


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _get_usage_count(uid: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT doc_count FROM usage_counters WHERE user_id=$1 AND period=$2",
            uid, _current_period(),
        )
    return val or 0


async def _check_and_inc_usage(uid: str) -> int:
    """Atomically check monthly limit and increment. Raises 429 if at limit."""
    period = _current_period()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Ensure row exists so FOR UPDATE has something to lock
            await conn.execute(
                """
                INSERT INTO usage_counters (user_id, period, doc_count)
                VALUES ($1, $2, 0)
                ON CONFLICT DO NOTHING
                """,
                uid, period,
            )
            current = await conn.fetchval(
                "SELECT doc_count FROM usage_counters WHERE user_id=$1 AND period=$2 FOR UPDATE",
                uid, period,
            ) or 0
            if current >= _MONTHLY_LIMIT:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Лимит исчерпан: {_MONTHLY_LIMIT} документов в месяц "
                        "на бесплатном тарифе."
                    ),
                )
            new_count = await conn.fetchval(
                """
                UPDATE usage_counters SET doc_count = doc_count + 1
                WHERE user_id=$1 AND period=$2
                RETURNING doc_count
                """,
                uid, period,
            )
    return new_count or 1


def _check_doc(pdf_bytes: bytes, filename: str, content_type: str | None = None) -> None:
    """Validate MIME, size, and page count. Raises 413/422."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ct = (content_type or "").lower().split(";")[0].strip()
    if ext not in _ALLOWED_DOC_EXTENSIONS and ct not in _ALLOWED_DOC_MIME:
        raise HTTPException(
            status_code=422,
            detail="Неподдерживаемый формат файла. Разрешены: PDF, DOC, DOCX.",
        )
    if len(pdf_bytes) > _MAX_DOC_SIZE:
        mb = len(pdf_bytes) / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой ({mb:.1f} МБ). Лимит кабинета: 5 МБ.",
        )
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        n = len(doc)
        doc.close()
    except HTTPException:
        raise
    except Exception:
        return  # unreadable PDF — let the pipeline report the error
    if n > _MAX_DOC_PAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Слишком много страниц ({n}). Лимит кабинета: {_MAX_DOC_PAGES} страниц.",
        )


def _preprocess_docx_for_libreoffice(docx_bytes: bytes) -> bytes:
    """Work around confirmed LibreOffice OOXML-import gaps in word/footer*.xml
    and word/header*.xml (this document has no headers — word/_rels/document.xml.rels
    carries zero header relationships, sectPr has no <w:headerReference> — the
    header branch is untested against real header XML, included for future
    documents that do have one; if there's nothing to match, the loop is a no-op).

    Fix-9 A.2 revised this against two real PDFs (not assumption): a genuine
    Word "Save As PDF" export (reference_word_export.pdf) and the RAW,
    unpatched LibreOffice conversion of the same DOCX. Measuring both directly
    with PyMuPDF settled all three Fix-8.C guesses — and Fix-9's own first
    attempt at #1 was itself re-measured against a real deployed conversion
    and found to still be wrong, corrected below:

      1. <w:ptab .../alignment="right"/>. Raw LO output put "Страница N"'s
         text-center at x=266pt (page width 595pt — centered). The Word
         reference has it at x=520pt (near the right margin). Fix-9's first
         attempt replaced the ptab run with a bare <w:tab/> and, without
         re-measuring the actual deployed output, was assumed to fix this.
         It didn't: measured against a real converted PDF, the bare tab
         landed at x=266.2 — byte-for-byte the same as doing nothing, because
         a tab character with no declared tab-stop has nowhere to jump to.
         Fixed properly now: inject an explicit right-aligned w:tabs entry
         into that paragraph's w:pPr, positioned at this document's own
         (page width − left margin − right margin), read from its own
         w:sectPr rather than hardcoded — plus the same bare-tab swap.
      2. Border/line color — CONFIRMED CORRECT by re-measurement. A real
         converted PDF renders the line at RGB(98,36,34) = #622422, matching
         the Word reference's #622423 (1-unit rounding). Stripping
         w:themeColor/w:themeTint/w:themeShade and keeping Word's own
         literal w:color fallback works as intended.
      3. Font — CONFIRMED CORRECT by re-measurement. A real converted PDF's
         font list includes "Caladea-Regular" — LibreOffice's own
         Cambria→Caladea substitution firing exactly as expected once the
         XML stopped overriding the font name to Liberation Serif.

    Returns modified DOCX bytes. If parsing fails — returns input unchanged
    (fail-safe, LibreOffice will render as-is).
    """
    import io
    import re
    import zipfile

    try:
        buf_in = io.BytesIO(docx_bytes)
        buf_out = io.BytesIO()
        with zipfile.ZipFile(buf_in, "r") as zin, \
             zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout:

            # Right-margin tab-stop position (twips from the left margin),
            # computed from this document's own section properties instead of
            # a hardcoded number — a bare <w:tab/> alone has nothing to jump
            # to and is a no-op (measured, see docstring point 1).
            right_tab_pos: int | None = None
            try:
                doc_xml = zin.read("word/document.xml").decode("utf-8", errors="ignore")
                pg_w_m = re.search(r'<w:pgSz\b[^>]*\bw:w="(\d+)"', doc_xml)
                pg_left_m = re.search(r'<w:pgMar\b[^>]*\bw:left="(\d+)"', doc_xml)
                pg_right_m = re.search(r'<w:pgMar\b[^>]*\bw:right="(\d+)"', doc_xml)
                if pg_w_m and pg_left_m and pg_right_m:
                    right_tab_pos = int(pg_w_m.group(1)) - int(pg_left_m.group(1)) - int(pg_right_m.group(1))
            except KeyError:
                pass  # no word/document.xml — not a valid docx, let soffice report it

            def _fix_ptab_paragraph(m: re.Match) -> str:
                para = m.group(0)
                para = re.sub(
                    r'<w:ptab\b[^/]*w:alignment="right"[^/]*/>',
                    '<w:tab/>',
                    para,
                )
                if right_tab_pos is not None:
                    tabs_xml = f'<w:tabs><w:tab w:val="right" w:pos="{right_tab_pos}"/></w:tabs>'
                    # w:tabs must sit after w:pBdr/w:shd and before w:rPr in
                    # w:pPr's fixed child order (ECMA-376) — insert at whichever
                    # of those boundaries is actually present in this paragraph.
                    if '</w:pBdr>' in para:
                        para = para.replace('</w:pBdr>', '</w:pBdr>' + tabs_xml, 1)
                    elif '<w:rPr>' in para:
                        para = para.replace('<w:rPr>', tabs_xml + '<w:rPr>', 1)
                    else:
                        para = para.replace('</w:pPr>', tabs_xml + '</w:pPr>', 1)
                return para

            for item in zin.infolist():
                data = zin.read(item.filename)
                if (item.filename.startswith("word/footer") or item.filename.startswith("word/header")) \
                        and item.filename.endswith(".xml"):
                    text = data.decode("utf-8", errors="ignore")

                    # 1. Paragraph containing a right-aligned positional tab:
                    #    inject an explicit right w:tabs entry + swap the ptab
                    #    run for a plain tab character.
                    text = re.sub(
                        r'<w:p\b.*?<w:ptab\b[^/]*w:alignment="right"[^/]*/>.*?</w:p>',
                        _fix_ptab_paragraph,
                        text,
                        flags=re.DOTALL,
                    )

                    # 2. Strip theme color resolution, keep Word's own literal
                    #    fallback (whichever attribute — w:val or w:color —
                    #    precedes it) untouched.
                    text = re.sub(
                        r'\s+w:themeColor="accent2"'
                        r'(\s+w:themeTint="[^"]*")?'
                        r'(\s+w:themeShade="[^"]*")?',
                        '',
                        text,
                    )

                    data = text.encode("utf-8")
                zout.writestr(item, data)
        return buf_out.getvalue()
    except Exception as e:
        logger.warning("DOCX preprocessing failed: %s, using original bytes", e)
        return docx_bytes


def _convert_to_pdf_if_needed(raw: bytes, filename: str, content_type: str | None) -> bytes:
    """Convert DOC/DOCX uploads to PDF via LibreOffice headless (soffice).

    LibreOffice is the same engine Word/Google Docs use for "Save As PDF" and
    preserves footers, headers, precise positioning, tables, centering, and
    fonts (with Liberation Serif/Sans/Mono as metric-compatible Times/Arial/
    Courier substitutes — see Dockerfile). The previous mammoth+weasyprint
    path only mapped Word to semantic HTML and lost all of the above.

    Returns raw bytes unchanged for PDF input.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ct = (content_type or "").lower().split(";")[0].strip()
    is_docx = ext in ("doc", "docx") or ct in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    )
    if not is_docx:
        return raw

    raw = _preprocess_docx_for_libreoffice(raw)

    with tempfile.TemporaryDirectory(prefix="sf-conv-") as tmpdir:
        safe_ext = ext if ext in ("doc", "docx") else "docx"
        input_path = Path(tmpdir) / f"in.{safe_ext}"
        input_path.write_bytes(raw)

        # soffice on a first cold call spends ~2–4s bootstrapping profile+JVM;
        # subsequent conversions in the same process are ~0.5–1s. A dedicated
        # per-request profile dir prevents concurrent workers from clobbering
        # each other's ~/.config/libreoffice.
        profile_url = f"-env:UserInstallation=file://{tmpdir}/profile"
        try:
            proc = subprocess.run(
                ["soffice", profile_url, "--headless", "--nologo", "--nolockcheck",
                 "--convert-to", "pdf", "--outdir", tmpdir, str(input_path)],
                capture_output=True, timeout=90, check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=422, detail="Конвертация Word→PDF заняла слишком много времени")

        output_pdf = input_path.with_suffix(".pdf")
        if proc.returncode != 0 or not output_pdf.exists():
            stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")[:300]
            logger.warning("soffice convert failed rc=%s stderr=%s", proc.returncode, stderr)
            raise HTTPException(status_code=422, detail="Не удалось конвертировать документ")

        return output_pdf.read_bytes()


# ── Fix-7: tenant-scoped template matching (Phase A) ───────────────────────────

def _tenant_template_match(tenant_storage: TenantScopedStorage, pdf_bytes: bytes, filename: str):
    """Try matching the doc against this tenant's own remembered templates.

    Mirrors the template-path branch of SignFinder.analyze() (signfinder-core),
    but against tenant_storage instead of the global storage, so a green match
    only comes from templates this tenant remembered via /me/templates/remember.

    Returns (doc, lang_fast, fingerprint, tpl, tpl_matches, tpl_anchors, debug).
    tpl is None when there's no usable green match — doc/lang_fast/fingerprint
    are still returned so the caller can reuse them on the LLM fallback path.

    Fix-9 B.1: `debug` carries diagnostics for the "remember saved, analyze
    finds nothing" symptom — listed unfiltered (before find_matching_templates'
    own language filter) so "physically 0 stored" can be told apart from
    "stored but filtered out by language" from pipeline_debug alone, without
    re-deriving it from guesswork every time it recurs.
    """
    import fitz

    from signfinder.fingerprint import compute_fingerprint
    from signfinder.pdf import detect_language_fast, parse_pdf_bytes
    from signfinder.pipeline import apply_template_to_doc
    from signfinder.templates import find_matching_templates, list_templates, load_template, update_usage_stats

    debug: dict = {"templates_storage_prefix": f"me/{tenant_storage._tenant_id}/templates/"}

    doc = parse_pdf_bytes(pdf_bytes, filename=filename)
    lang_fast = detect_language_fast(doc) or "ru"
    debug["templates_match_language"] = lang_fast

    fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        fingerprint = compute_fingerprint(fitz_doc, lang_fast)

        all_templates = list_templates(tenant_storage)  # unfiltered — see debug docstring above
        debug["templates_listed_count"] = len(all_templates)
        debug["templates_listed_languages"] = [t.language for t in all_templates]

        matcher = find_matching_templates(
            fitz_doc, lang_fast, storage=tenant_storage, fingerprint=fingerprint,
        )
    finally:
        fitz_doc.close()

    debug["templates_traffic_light"] = matcher.traffic_light
    debug["best_match_score_details"] = (
        {
            "template_id": matcher.best_match.template_id,
            "score": matcher.best_match.score,
            "score_breakdown": matcher.best_match.score_breakdown,
            "synonyms_match": matcher.best_match.synonyms_match,
        }
        if matcher.best_match else None
    )

    if matcher.traffic_light == "green" and matcher.best_match:
        tpl = load_template(tenant_storage, matcher.best_match.template_id)
        if tpl is not None:
            tpl_matches, tpl_anchors = apply_template_to_doc(doc, tpl, lang_fast)
            if tpl_anchors:
                try:
                    update_usage_stats(tenant_storage, matcher.best_match.template_id, "applied")
                except Exception:
                    logger.warning("update_usage_stats failed for %s", matcher.best_match.template_id)
                return doc, lang_fast, fingerprint, tpl, tpl_matches, tpl_anchors, debug

    return doc, lang_fast, fingerprint, None, None, None, debug


def _build_synonyms_used(doc, language: str, our_side: dict) -> dict:
    """Same synonyms_used shape as save_pipeline_template() (signfinder-core),
    so a template saved via /me/templates/remember matches/names consistently
    with templates saved by the internal pipeline.
    """
    from signfinder.pipeline.auto1 import _extract_contract_type, _extract_counterparty

    return {
        "legal_entity": our_side.get("legal_entity", ""),
        "roles": our_side.get("roles", []),
        "signer": our_side.get("signer", ""),
        "contract_type": _extract_contract_type(doc, language),
        "counterparty": _extract_counterparty(our_side),
    }


# ── models ────────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = ""
    company: str = ""
    requisites: str = ""


class ProfileOut(BaseModel):
    full_name: str
    company: str
    requisites: str


class SignatureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    png_b64: str  # base64 of processed PNG from /process endpoint


class PartyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    role: str = ""


class PartyOut(BaseModel):
    name: str
    role: str


class UsageOut(BaseModel):
    doc_count: int
    limit: int
    period: str


class RememberTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: dict
    anchors: list
    language: str
    synonyms_used: dict = {}


class RememberTemplateOut(BaseModel):
    template_id: str
    name: str


# ── profile ───────────────────────────────────────────────────────────────────

@router.get("/me/profile", response_model=ProfileOut)
async def get_profile(user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT full_name, company, requisites_json FROM profiles WHERE user_id = $1",
            uid,
        )
    if row is None:
        return ProfileOut(full_name="", company="", requisites="")
    req_raw = row["requisites_json"] or {}
    return ProfileOut(
        full_name=row["full_name"] or "",
        company=row["company"] or "",
        requisites=req_raw.get("text", "") if isinstance(req_raw, dict) else "",
    )


@router.put("/me/profile", response_model=ProfileOut)
async def put_profile(body: ProfileIn, user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO profiles (user_id, full_name, company, requisites_json, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET full_name       = EXCLUDED.full_name,
                  company         = EXCLUDED.company,
                  requisites_json = EXCLUDED.requisites_json,
                  updated_at      = NOW()
            """,
            uid,
            body.full_name,
            body.company,
            {"text": body.requisites},
        )
    return ProfileOut(
        full_name=body.full_name,
        company=body.company,
        requisites=body.requisites,
    )


# ── signature ─────────────────────────────────────────────────────────────────

@router.post("/me/signature/process")
async def process_signature_ep(
    user: UserDep,
    file: UploadFile = File(...),
) -> Any:
    """OpenCV-process a signature image — preview only, does NOT save."""
    ct = (file.content_type or "").lower()
    if not ct.startswith("image/"):
        raise HTTPException(status_code=422, detail="Только изображения (PNG/JPG/HEIC)")
    raw = await file.read()
    if len(raw) > _MAX_SIG_UPLOAD:
        raise HTTPException(status_code=422, detail="Файл слишком большой (макс 5МБ)")
    try:
        from signfinder.signature import process_signature
        result = process_signature(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Ошибка обработки: {exc}")
    return {
        "processed_png_b64": base64.b64encode(result.png_bytes).decode(),
        "confidence": result.confidence,
        "warnings": result.warnings,
        "output_size": result.output_size,
        "ink_coverage": result.ink_coverage,
    }


@router.get("/me/signature")
async def get_signature(user: UserDep) -> Response:
    """Download current signature as image/png. 404 if not uploaded yet."""
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT png_bytes FROM signatures WHERE user_id = $1 AND png_bytes IS NOT NULL",
            uid,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Подпись не найдена")
    return Response(content=bytes(row["png_bytes"]), media_type="image/png")


@router.put("/me/signature", status_code=204)
async def put_signature(body: SignatureIn, user: UserDep) -> None:
    """Save processed signature (base64 PNG) to DB. One per user, overwrites."""
    uid = user["firebase_uid"]
    try:
        png_bytes = base64.b64decode(body.png_b64)
    except Exception:
        raise HTTPException(status_code=422, detail="Невалидный base64")
    if len(png_bytes) > _MAX_SIG_PNG:
        raise HTTPException(status_code=422, detail="PNG слишком большой (макс 500КБ)")
    if not png_bytes.startswith(b"\x89PNG"):
        raise HTTPException(status_code=422, detail="Ожидается PNG (неверный формат)")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO signatures (user_id, png_bytes, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET png_bytes = EXCLUDED.png_bytes, updated_at = NOW()
            """,
            uid, png_bytes,
        )


# ── party ─────────────────────────────────────────────────────────────────────

@router.get("/me/party", response_model=PartyOut)
async def get_party(user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, role FROM parties WHERE user_id = $1",
            uid,
        )
    if row is None:
        return PartyOut(name="", role="")
    return PartyOut(name=row["name"] or "", role=row["role"] or "")


@router.put("/me/party", response_model=PartyOut)
async def put_party(body: PartyIn, user: UserDep) -> Any:
    uid = user["firebase_uid"]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO parties (user_id, name, role, patterns_json, updated_at)
            VALUES ($1, $2, $3, '[]'::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET name = EXCLUDED.name, role = EXCLUDED.role, updated_at = NOW()
            """,
            uid, body.name, body.role,
        )
    return PartyOut(name=body.name, role=body.role)


# ── usage ─────────────────────────────────────────────────────────────────────

@router.get("/me/usage", response_model=UsageOut)
async def get_usage(user: UserDep) -> UsageOut:
    """Return current-month document usage for this user."""
    uid = user["firebase_uid"]
    count = await _get_usage_count(uid)
    return UsageOut(doc_count=count, limit=_MONTHLY_LIMIT, period=_current_period())


# ── M3: cabinet pipeline ──────────────────────────────────────────────────────

@router.post("/me/convert")
async def me_convert(
    user: UserDep,
    file: UploadFile = File(...),
) -> Response:
    """Convert a DOC/DOCX upload to PDF for the cabinet preview.

    Uses the same LibreOffice path as /me/analyze so the pre-signing preview
    is byte-identical to what gets signed. For PDF uploads this returns the
    original file unchanged (client can skip the round-trip).
    """
    uid = user["firebase_uid"]
    raw = await file.read()
    filename = file.filename or "document.docx"
    if len(raw) > _MAX_DOC_SIZE:
        mb = len(raw) / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой ({mb:.1f} МБ). Лимит кабинета: 5 МБ.",
        )
    try:
        pdf_bytes = _convert_to_pdf_if_needed(raw, filename, file.content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("me/convert failed for user %s: %s", uid, e)
        raise HTTPException(status_code=422, detail="Не удалось конвертировать документ")
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/me/analyze")
async def me_analyze(
    user: UserDep,
    sf: SignFinderDep,
    file: UploadFile = File(...),
) -> Any:
    """Analyze a contract (JWT-protected, 5 MB / 3 pages / 10 docs/month).

    Document is processed in RAM only — never written to disk, DB, or GCS.
    Prompt-injection isolation handled by signfinder-core:
      - document text in user role with untrusted-input wrapper
      - system instructions in separate system role
      - LLM output validated against JSON schema
      - LLM-produced anchors verified against actual PDF text
    """
    uid = user["firebase_uid"]

    # Check monthly limit before burning LLM tokens
    count = await _get_usage_count(uid)
    if count >= _MONTHLY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Лимит исчерпан: {_MONTHLY_LIMIT} документов в месяц на бесплатном тарифе.",
        )

    raw_bytes = await file.read()
    filename = file.filename or "document.pdf"
    pdf_bytes = _convert_to_pdf_if_needed(raw_bytes, filename, file.content_type)
    _check_doc(pdf_bytes, filename, file.content_type)

    tenant_storage = TenantScopedStorage(sf.storage, uid)

    # Fix-7 Phase A: try this tenant's own remembered templates before the LLM.
    # Failure here must never break analysis — fall through to the LLM path.
    doc = lang_fast = fingerprint = tpl = tpl_matches = tpl_anchors = None
    tenant_debug: dict = {}
    try:
        doc, lang_fast, fingerprint, tpl, tpl_matches, tpl_anchors, tenant_debug = _tenant_template_match(
            tenant_storage, pdf_bytes, filename,
        )
    except Exception as e:
        logger.warning("me/analyze tenant template match failed for user %s: %s", uid, e)

    if tpl is not None:
        from signfinder import AnalysisResult

        result = AnalysisResult(
            traffic_light="green",
            anchors=tpl_anchors,
            matches=tpl_matches,
            fingerprint=fingerprint,
            pipeline_debug=tenant_debug,
        )
        resp = AnalysisResponse.from_result(result)
        resp.from_template = True
        resp.template_id = tpl.template_id
        resp.template_name = tpl.name
        resp.synonyms_used = tpl.synonyms_used
        return resp

    try:
        result = sf.analyze(
            pdf_bytes,
            filename=file.filename or "document.pdf",
        )
    except Exception as e:
        logger.warning("me/analyze failed for user %s: %s", uid, e)
        return AnalysisResponse(
            traffic_light="no_match",
            anchors=[],
            matches=[],
            matched_template=None,
            applied_template_id=None,
            our_side=None,
            error=str(e),
            pipeline_debug=tenant_debug,
            from_template=False,
        )

    resp = AnalysisResponse.from_result(result)
    resp.from_template = False
    resp.pipeline_debug = {**tenant_debug, **(resp.pipeline_debug or {})}
    if resp.fingerprint is None:
        resp.fingerprint = fingerprint
    if doc is not None and lang_fast and result.our_side:
        try:
            resp.synonyms_used = _build_synonyms_used(doc, lang_fast, result.our_side)
        except Exception as e:
            logger.warning("me/analyze synonyms_used build failed for user %s: %s", uid, e)
            resp.synonyms_used = {}
    else:
        resp.synonyms_used = {}
    return resp


# ── Fix-7 Phase A.3: remember / forget templates (tenant-scoped) ───────────────

@router.post("/me/templates/remember", response_model=RememberTemplateOut)
async def remember_template(body: RememberTemplateIn, user: UserDep, sf: SignFinderDep) -> Any:
    """Save the last-analyzed document as a reusable template for this tenant.

    Takes fingerprint/anchors/synonyms_used straight from a prior /me/analyze
    response — the file is never re-uploaded or re-parsed.
    """
    from signfinder.templates import new_template, save_template

    uid = user["firebase_uid"]
    tenant_storage = TenantScopedStorage(sf.storage, uid)

    tpl = new_template(
        language=body.language,
        anchors=body.anchors,
        fingerprint=body.fingerprint,
        synonyms_used=body.synonyms_used,
        created_by="cabinet_remember",
    )
    try:
        save_template(tenant_storage, tpl)
    except Exception as e:
        logger.exception("remember_template failed for user %s", uid)
        raise HTTPException(status_code=500, detail=str(e))

    return RememberTemplateOut(template_id=tpl.template_id, name=tpl.name)


@router.delete("/me/templates/{template_id}", status_code=204)
async def forget_template(template_id: str, user: UserDep, sf: SignFinderDep) -> None:
    """Forget a remembered template. 404 if not found (including other users' —
    tenant scoping makes those physically absent from this tenant's prefix)."""
    from signfinder.templates import delete_template

    uid = user["firebase_uid"]
    tenant_storage = TenantScopedStorage(sf.storage, uid)

    deleted = delete_template(tenant_storage, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Шаблон '{template_id}' не найден")


class ManualAnchorProbeOut(BaseModel):
    anchor_text: str
    anchor_bbox: list[float] | None  # [x0,y0,x1,y1] pt, найденного текста-ориентира
    offset_dx: float                  # смещение от anchor_bbox.x0 до placed bbox.x
    offset_dy: float                  # смещение от anchor_bbox.y0 до placed bbox.y


@router.post("/me/manual-anchor/probe", response_model=ManualAnchorProbeOut)
async def probe_manual_anchor(
    user: UserDep,
    file: UploadFile = File(...),
    page: int = Form(...),          # 1-indexed
    x: float = Form(...),
    y: float = Form(...),
    width: float = Form(...),
    height: float = Form(...),
) -> Any:
    """Find the nearest text landmark for a manually-placed signature spot and
    return the placed bbox's offset from it.

    Called once when the operator confirms a manual click (✓ in the UI) —
    before the point is added to _manualAnchors. No side effects, the file is
    not saved (same principle as /me/signature/process).
    """
    raw = await file.read()
    filename = file.filename or "document.pdf"
    pdf_bytes = _convert_to_pdf_if_needed(raw, filename, file.content_type)

    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_idx = page - 1
        if page_idx < 0 or page_idx >= len(doc):
            raise HTTPException(status_code=422, detail="Неверный номер страницы")
        pdf_page = doc[page_idx]

        # get_text("words") -> [(x0,y0,x1,y1,text,block_no,line_no,word_no), ...]
        words = pdf_page.get_text("words")
        click_cx, click_cy = x + width / 2, y + height / 2

        def _dist(w):
            wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
            wcx, wcy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
            return ((wcx - click_cx) ** 2 + (wcy - click_cy) ** 2) ** 0.5

        # Радиус поиска — 150pt, дальше считаем что рядом ничего значимого нет
        nearby = [w for w in words if _dist(w) <= 150 and len(w[4].strip()) >= 2]
        if not nearby:
            return ManualAnchorProbeOut(
                anchor_text="", anchor_bbox=None, offset_dx=0.0, offset_dy=0.0,
            )

        nearest = min(nearby, key=_dist)
        nx0, ny0 = nearest[0], nearest[1]
        return ManualAnchorProbeOut(
            anchor_text=nearest[4],
            anchor_bbox=[nearest[0], nearest[1], nearest[2], nearest[3]],
            offset_dx=x - nx0,
            offset_dy=y - ny0,
        )
    finally:
        doc.close()


@router.post("/me/sign")
async def me_sign(
    user: UserDep,
    sf: SignFinderDep,
    file: UploadFile = File(...),
    anchors_json: str = Form(...),
    signature_scale: float = Form(1.0),
    manual_anchors_json: str = Form("[]"),
    exclude_pages_json: str = Form("[]"),
) -> Response:
    """Sign a contract using the user's stored signature (JWT-protected).

    Order of checks:
      1. Signature exists in DB    (422 if missing)
      2. PDF size / page count     (413 / 422)
      3. Atomic usage check + inc  (429 if at limit)
      4. Sign → return PDF
    Document is processed in RAM only — never persisted.

    Fix-7 Phase B: manual_anchors_json — freeform placements from the cabinet's
    drag/resize UI: [{page, x, y, width, height}], page 1-indexed, x/y/width/
    height in PDF points. exclude_pages_json — 1-indexed pages to drop existing
    (LLM/template) anchors from; manual placements are never auto-excluded.
    """
    uid = user["firebase_uid"]

    # 1. Fetch user's PNG — 422 if not uploaded yet
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT png_bytes FROM signatures WHERE user_id=$1 AND png_bytes IS NOT NULL",
            uid,
        )
    if row is None:
        raise HTTPException(
            status_code=422,
            detail="Подпись не загружена. Перейдите на вкладку «Подпись» и загрузите подпись.",
        )
    png_bytes = bytes(row["png_bytes"])

    # 2. Read, convert (DOC/DOCX → PDF), and validate PDF
    raw_bytes = await file.read()
    filename = file.filename or "document.pdf"
    pdf_bytes = _convert_to_pdf_if_needed(raw_bytes, filename, file.content_type)
    _check_doc(pdf_bytes, filename, file.content_type)

    # 3. Parse anchors + Fix-7 manual placements / page exclusions
    try:
        anchors = json.loads(anchors_json)
        manual_anchors = json.loads(manual_anchors_json)
        exclude_pages = set(json.loads(exclude_pages_json))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=422,
            detail="anchors_json/manual_anchors_json/exclude_pages_json: невалидный JSON",
        )
    if not anchors and not manual_anchors:
        raise HTTPException(status_code=422, detail="Нет якорей для подписи")

    # 4. Atomic usage check + increment (429 if at limit)
    await _check_and_inc_usage(uid)

    # 5. Build TextAnchor objects
    from signfinder.anchors import TextAnchor
    now_iso = datetime.now(timezone.utc).isoformat()
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
                added_by=a.get("added_by", "auto_regex"),
                added_at=a.get("added_at", now_iso),
                bbox=tuple(bbox),
            ))
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Невалидный якорь {a}: {e}")

    # Fix-7: drop anchors on excluded pages ("удалить подпись на текущей странице").
    # Resolves page_hint ("first"/"last"/int) via the same _to_match SignFinder
    # already uses internally, so exclusion matches exactly what would be signed.
    if exclude_pages and anchor_objects:
        try:
            import fitz
            with fitz.open(stream=pdf_bytes, filetype="pdf") as _doc:
                total_pages = len(_doc)
        except Exception:
            total_pages = 0

        def _page_1idx(a) -> int:
            p = sf._to_match(a).page
            if p < 0:
                p = total_pages + p  # "last" resolves to -1 → wrap to real index
            return p + 1

        anchor_objects = [a for a in anchor_objects if _page_1idx(a) not in exclude_pages]

    # Fix-7 Phase B: freeform manual placements (drag/resize UI). added_by=
    # "manual_exact" makes apply_signature() (signfinder-core) place the PNG
    # literally at this bbox instead of searching the page for a nearby anchor.
    from signfinder.anchors import SignMatch
    manual_matches = []
    for i, m in enumerate(manual_anchors):
        try:
            page = int(m["page"])
            x, y = float(m["x"]), float(m["y"])
            w, h = float(m["width"]), float(m["height"])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"Невалидный manual_anchor {m}: {e}")
        manual_matches.append(SignMatch(
            id=f"manual_{i}",
            page=page - 1,
            bbox=(x, y, x + w, y + h),
            context="",
            party="manual",
            pattern="",
            confidence=1.0,
            added_by="manual_exact",
        ))

    all_matches = anchor_objects + manual_matches
    if not all_matches:
        raise HTTPException(status_code=422, detail="Нет якорей для подписи")

    # 6. Sign — user's real signature, no marker
    try:
        signed_bytes = sf.sign(
            pdf_bytes,
            all_matches,
            png_bytes,
            scale=signature_scale,
            use_signature=True,
            use_marker=False,
            marker_color="pink",
        )
    except Exception as e:
        logger.exception("me/sign failed for user %s", uid)
        raise HTTPException(status_code=422, detail=str(e))

    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    raw_name = f"signed_{base_name}.pdf"
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
