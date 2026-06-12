"""Pydantic-схемы для /v1/signers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AliasEntry(BaseModel):
    language: str          # "ru", "en", "pl", "mk"
    value: str             # "Innowise Sp. z o.o"


class SignerProfileResponse(BaseModel):
    id: str
    display: str = ""
    match_markers: list[str] = []
    company_aliases: list[AliasEntry] = []
    signer_aliases: list[AliasEntry] = []
    has_signature: bool = False
    updated_at: str = ""


class SignerProfileCreate(BaseModel):
    """Создание нового профиля."""
    id: str                              # "borisov", "lebedev" — slug, без пробелов
    display: str = ""                    # "Vadim Borisov / Innowise"
    match_markers: list[str] = []        # ["Innowise", "Vadim Borisov", "Вадим Борисов"]
    company_aliases: list[AliasEntry] = []
    signer_aliases: list[AliasEntry] = []


class SignerProfileUpdate(BaseModel):
    """Частичное обновление профиля (все поля опциональны)."""
    display: Optional[str] = None
    match_markers: Optional[list[str]] = None
    company_aliases: Optional[list[AliasEntry]] = None
    signer_aliases: Optional[list[AliasEntry]] = None
