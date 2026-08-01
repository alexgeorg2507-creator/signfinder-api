"""POST /v1/feedback — SignfinderLand v2.0.0 Deal Cycle, эпик E6.

За Firebase Auth (UserDep) — форма живёт в кабинете, пользователь уже
залогинен. Единственное действие: собрать ответ в текст и отправить одним
сообщением в личный Telegram-чат владельца через Bot API. Никакого диалога
с пользователем в Telegram нет — он никогда не видит Telegram напрямую.

DEAL_CYCLE_SPEC.md §8 E6.
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.routers.me import UserDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Feedback"])

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10.0


class UsageType(str, Enum):
    FREELANCER = "freelancer"
    SMALL_BUSINESS = "small_business"
    LEGAL_DEPT = "legal_dept"
    OTHER = "other"


class PremiumFeature(str, Enum):
    LOCAL_DEPLOYMENT = "local_deployment"      # "Локальная установка — документы не покидают вашу инфраструктуру"
    TWO_SIDED_SIGNING = "two_sided_signing"    # "Двустороннее подписание через сервис"
    HIGHER_LIMITS = "higher_limits"            # "Расширенные лимиты объёма документов"
    API_INTEGRATIONS = "api_integrations"      # "API/интеграции (Cursor, Claude Desktop и т.п.)"
    TEAM_ACCESS = "team_access"                # "Командный доступ — несколько сотрудников на аккаунт"


# fix15 §5.1: полная замена опросника — старая форма (feature_request/source)
# ещё не была в реальном использовании (прод не задеплоен), мигрировать
# нечего, старые поля убраны, а не оставлены рядом.
class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usage_type: Optional[UsageType] = None
    premium_features: list[PremiumFeature] = []
    premium_features_other: Optional[str] = None
    would_refer: Optional[bool] = None
    contact: Optional[str] = None


_USAGE_TYPE_LABEL = {
    UsageType.FREELANCER: "Фрилансер / ИП",
    UsageType.SMALL_BUSINESS: "Малый бизнес",
    UsageType.LEGAL_DEPT: "Юридический отдел / агентство",
    UsageType.OTHER: "Другое",
}

_PREMIUM_FEATURE_LABEL = {
    PremiumFeature.LOCAL_DEPLOYMENT: "Локальная установка",
    PremiumFeature.TWO_SIDED_SIGNING: "Двустороннее подписание через сервис",
    PremiumFeature.HIGHER_LIMITS: "Расширенные лимиты объёма документов",
    PremiumFeature.API_INTEGRATIONS: "API/интеграции",
    PremiumFeature.TEAM_ACCESS: "Командный доступ",
}


def _format_message(email: str, body: FeedbackRequest) -> str:
    usage_type = _USAGE_TYPE_LABEL[body.usage_type] if body.usage_type else "не указано"

    feature_labels = [_PREMIUM_FEATURE_LABEL[f] for f in body.premium_features]
    other = body.premium_features_other.strip() if body.premium_features_other and body.premium_features_other.strip() else ""
    if other:
        feature_labels.append(f"другое: {other}")
    premium_features = ", ".join(feature_labels) if feature_labels else "не указано"

    if body.would_refer is None:
        would_refer = "не отвечено"
    else:
        would_refer = "да" if body.would_refer else "нет"
    contact = body.contact.strip() if body.contact and body.contact.strip() else "не указано"

    return (
        "💬 Фидбек SignFinder\n"
        f"От: {email}\n"
        f"Использует как: {usage_type}\n"
        f"Готов платить за: {premium_features}\n"
        f"Порекомендовал бы коллеге: {would_refer}\n"
        f"Контакт: {contact}"
    )


@router.post("/feedback", status_code=200)
async def submit_feedback(body: FeedbackRequest, user: UserDep) -> dict:
    """Всегда 200 пользователю, даже если доставка в Telegram не удалась —
    фидбек не критичен для флоу кабинета, а неудачную доставку пользователь
    не должен видеть как техническую ошибку. Сбой логируется на ERROR,
    чтобы не потеряться молча в Cloud Logging."""
    email = user.get("email") or user["firebase_uid"]
    text = _format_message(email, body)

    # .strip(): a secret provisioned via `"value" | gcloud secrets create
    # ... --data-file=-` in PowerShell picks up a trailing CRLF from the
    # pipe (observed live: httpx.InvalidURL on a bare \r right after the
    # token) — stripping here means a stray newline in how a secret was
    # created can never break the call again, regardless of provisioning
    # method.
    bot_token = (os.environ.get("TG_FEEDBACK_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TG_FEEDBACK_CHAT_ID") or "").strip()
    if not bot_token or not chat_id:
        logger.error("Feedback not delivered: TG_FEEDBACK_BOT_TOKEN/TG_FEEDBACK_CHAT_ID not configured")
        return {"status": "received"}

    url = _TELEGRAM_API_URL.format(token=bot_token)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
        if resp.status_code != 200:
            logger.error("Feedback not delivered: Telegram API %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Feedback not delivered: Telegram call failed: %r", exc)

    return {"status": "received"}
