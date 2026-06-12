"""LLM config endpoints: GET/POST /v1/config/llm, POST /v1/config/llm/test."""
from __future__ import annotations

import copy
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from signfinder.llm import (
    available_providers,
    configured_providers,
    load_config,
    mask_key,
    save_config,
)
from signfinder.llm.base import LLMError
from signfinder.llm.factory import create_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/config/llm", tags=["LLM Config"])

_TEST_SYSTEM = "You are a connectivity test assistant."
_TEST_USER = "Reply with JSON object containing key 'ok' with boolean value true."
_TEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


class LLMConfigIn(BaseModel):
    active_provider: str
    providers: dict[str, dict[str, str]]


class LLMTestIn(BaseModel):
    provider: str
    api_key: str | None = None  # несохранённый ключ для тестирования до сохранения


@router.get("")
def get_llm_config() -> dict[str, Any]:
    """Текущий конфиг с маскированными ключами."""
    config = load_config()
    masked: dict[str, Any] = {
        "active_provider": config.get("active_provider", ""),
        "providers": {},
        "configured": configured_providers(config),
        "available": available_providers(),
    }
    for provider, data in config.get("providers", {}).items():
        key = data.get("api_key", "")
        masked["providers"][provider] = {
            "api_key": mask_key(key),
            "configured": bool(key.strip()),
        }
    return masked


@router.post("")
def post_llm_config(body: LLMConfigIn) -> dict[str, str]:
    """Сохранить конфиг.

    Пустые/маскированные ключи → сохраняем существующий (из JSON или env var).
    После сохранения — сбрасываем синглтон SignFinder, чтобы следующий запрос
    создал новый экземпляр с актуальным LLM-провайдером.
    """
    existing = load_config()
    new_config: dict[str, Any] = {
        "active_provider": body.active_provider,
        "providers": {},
    }
    for provider in available_providers():
        incoming_key = body.providers.get(provider, {}).get("api_key", "").strip()
        if not incoming_key or "***" in incoming_key:
            # Берём существующий ключ — сначала из JSON, затем из env var
            existing_key = existing.get("providers", {}).get(provider, {}).get("api_key", "").strip()
            if not existing_key:
                try:
                    from signfinder.llm.config import get_api_key as _get_existing
                    existing_key = _get_existing(provider)
                except RuntimeError:
                    existing_key = ""
            new_config["providers"][provider] = {"api_key": existing_key}
        else:
            new_config["providers"][provider] = {"api_key": incoming_key}

    save_config(new_config)
    logger.info("LLM config saved. active_provider=%s", body.active_provider)

    # Сбрасываем синглтон SignFinder — следующий запрос создаст новый
    # экземпляр с актуальным провайдером из llm_config.json
    try:
        from app.dependencies import get_signfinder
        get_signfinder.cache_clear()
        logger.info("SignFinder singleton cleared, will reinit on next request")
    except Exception as _e:
        logger.warning("cache_clear failed: %s", _e)

    return {"status": "saved", "active_provider": body.active_provider}


@router.post("/test")
def test_llm_connection(body: LLMTestIn) -> dict[str, Any]:
    """Тест подключения к провайдеру.

    Если передан api_key — сохраняет его в конфиг (мержит с существующим),
    тестирует. Ключ остаётся в конфиге — пользователь только что его проверил
    и скорее всего нажмёт «Сохранить». Синглтон НЕ сбрасывается (только Save делает это).
    """
    incoming_key = (body.api_key or "").strip()

    if incoming_key:
        # Сохраняем новый ключ (мерж с существующим конфигом)
        existing = load_config()
        temp = copy.deepcopy(existing)
        temp.setdefault("providers", {})[body.provider] = {"api_key": incoming_key}
        save_config(temp)
        logger.info("LLM test: saved key for %s before testing", body.provider)

    try:
        client = create_client(body.provider)
        result = client.complete_structured(_TEST_SYSTEM, _TEST_USER, _TEST_SCHEMA)
        return {"provider": body.provider, "success": bool(result.get("ok")), "error": None}
    except LLMError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("LLM test failed: provider=%s", body.provider)
        raise HTTPException(status_code=500, detail=str(e))
