"""Criterion #11 (DEAL_CYCLE_SPEC.md §9) — no backend email sending anywhere
in this codebase, ever (ADR-010). See RUNBOOK_TESTING.md."""
from __future__ import annotations

import re
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent / "app"
_SMTP_PATTERN = re.compile(r"^\s*(import smtplib|from email\.)", re.MULTILINE)


def test_no_smtp_imports_anywhere():
    offenders = []
    for path in _APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _SMTP_PATTERN.search(text):
            offenders.append(str(path))
    assert offenders == [], f"Found smtplib/email imports in: {offenders}"
