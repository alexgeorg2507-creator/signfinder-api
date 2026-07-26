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
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.routers.me import UserDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Feedback"])

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10.0


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_request: str
    source: Optional[str] = None
    would_refer: Optional[bool] = None
    contact: Optional[str] = None


def _format_message(email: str, body: FeedbackRequest) -> str:
    source = body.source.strip() if body.source and body.source.strip() else "не указано"
    if body.would_refer is None:
        would_refer = "не отвечено"
    else:
        would_refer = "да" if body.would_refer else "нет"
    contact = body.contact.strip() if body.contact and body.contact.strip() else "не указано"

    return (
        "💬 Фидбек SignFinder\n"
        f"От: {email}\n"
        f"За какую фичу готов платить: {body.feature_request}\n"
        f"Как узнал о SignFinder: {source}\n"
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

    bot_token = os.environ.get("TG_FEEDBACK_BOT_TOKEN")
    chat_id = os.environ.get("TG_FEEDBACK_CHAT_ID")
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
