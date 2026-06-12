"""Pydantic-схемы для /v1/parties."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PartyResponse(BaseModel):
    name: str
    patterns: list[str] = []
    language: Optional[str] = None


class PartyCreate(BaseModel):
    name: str
    patterns: list[str] = []
    language: Optional[str] = "ru"


class PartyUpdate(BaseModel):
    patterns: Optional[list[str]] = None
    language: Optional[str] = None
