"""Settings: /v1/settings/traffic-light, /markers, /retention, /sign-mode.

Конфиги хранятся в storage как settings/{name}.json.
v1.14.0: добавлен /settings/sign-mode + исправлен StorageBackend API
  (было: sf.storage.read()/.write() — не существуют → AttributeError в рантайме;
   стало: sf.storage.read_json()/.write_json() — по DEPLOY_CONSTRAINTS.md).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.dependencies import ApiKeyDep, SignFinderDep
from app.models.settings import MailConfig, MarkersConfig, RetentionConfig, SignModeConfig, TrafficLightConfig

logger = logging.getLogger(__name__)
router = APIRouter()


def _read_setting(sf, name: str, default: dict) -> dict:
    data = sf.storage.read_json(f"settings/{name}.json")
    return data if data is not None else default


def _write_setting(sf, name: str, data: dict) -> None:
    sf.storage.write_json(f"settings/{name}.json", data)


# ── Traffic light ─────────────────────────────────────────────────────────────

@router.get("/settings/traffic-light", response_model=TrafficLightConfig)
async def get_traffic_light(_: ApiKeyDep, sf: SignFinderDep):
    data = _read_setting(sf, "traffic_light", {"green_threshold": 0.85, "yellow_threshold": 0.60})
    return TrafficLightConfig(**data)


@router.put("/settings/traffic-light", response_model=TrafficLightConfig)
async def put_traffic_light(_: ApiKeyDep, sf: SignFinderDep, config: TrafficLightConfig):
    try:
        _write_setting(sf, "traffic_light", config.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return config


# ── Markers ───────────────────────────────────────────────────────────────────

@router.get("/settings/markers", response_model=MarkersConfig)
async def get_markers(_: ApiKeyDep, sf: SignFinderDep):
    data = _read_setting(sf, "markers", {"ru": [], "en": [], "pl": []})
    return MarkersConfig(**data)


@router.put("/settings/markers", response_model=MarkersConfig)
async def put_markers(_: ApiKeyDep, sf: SignFinderDep, config: MarkersConfig):
    try:
        _write_setting(sf, "markers", config.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return config


# ── Retention ─────────────────────────────────────────────────────────────────

@router.get("/settings/retention", response_model=RetentionConfig)
async def get_retention(_: ApiKeyDep, sf: SignFinderDep):
    data = _read_setting(sf, "retention", {"enabled": False, "max_age_days": 90})
    return RetentionConfig(**data)


@router.put("/settings/retention", response_model=RetentionConfig)
async def put_retention(_: ApiKeyDep, sf: SignFinderDep, config: RetentionConfig):
    try:
        _write_setting(sf, "retention", config.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return config


@router.post("/settings/retention/run", status_code=202)
async def run_retention(_: ApiKeyDep, sf: SignFinderDep):
    """Запустить ретенцию вручную. В v1.9 — заглушка."""
    raise HTTPException(
        status_code=501,
        detail="Manual retention run not implemented in v1.9.",
    )


# ── Sign mode ─────────────────────────────────────────────────────────────────

_SIGN_MODE_DEFAULT = {"use_signature": True, "use_marker": False, "marker_color": "pink"}


@router.get("/settings/sign-mode", response_model=SignModeConfig)
async def get_sign_mode(_: ApiKeyDep, sf: SignFinderDep):
    data = _read_setting(sf, "sign_mode", _SIGN_MODE_DEFAULT)
    return SignModeConfig(**data)


@router.put("/settings/sign-mode", response_model=SignModeConfig)
async def put_sign_mode(_: ApiKeyDep, sf: SignFinderDep, config: SignModeConfig):
    try:
        _write_setting(sf, "sign_mode", config.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return config


# ── Mail config ───────────────────────────────────────────────────────────────

_MAIL_CONFIG_DEFAULT: dict = MailConfig().model_dump()


@router.get("/settings/mail-config", response_model=MailConfig)
async def get_mail_config(_: ApiKeyDep, sf: SignFinderDep):
    data = _read_setting(sf, "mail_config", _MAIL_CONFIG_DEFAULT)
    return MailConfig(**{k: data.get(k, v) for k, v in _MAIL_CONFIG_DEFAULT.items()})


@router.put("/settings/mail-config", response_model=MailConfig)
async def put_mail_config(_: ApiKeyDep, sf: SignFinderDep, config: MailConfig):
    try:
        _write_setting(sf, "mail_config", config.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return config
