"""Pydantic-схемы для /v1/settings."""
from __future__ import annotations

from pydantic import BaseModel


class TrafficLightConfig(BaseModel):
    green_threshold: float = 0.85
    yellow_threshold: float = 0.60


class MarkersConfig(BaseModel):
    ru: list[str] = []
    en: list[str] = []
    pl: list[str] = []


class RetentionConfig(BaseModel):
    enabled: bool = False
    max_age_days: int = 90


class SignModeConfig(BaseModel):
    use_signature: bool = True
    use_marker: bool = False
    marker_color: str = "pink"  # "pink" | "gray"
    sign_above_line: bool = False
    default_page: str = "last"  # "first" | "last" — initial page in Разбор


class MailConfig(BaseModel):
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    poll_interval_sec: int = 300
    reply_to_sender: bool = False
    folder_in: str = "SignfinderIn"
    folder_green: str = "SignfinderGreen"
    folder_yellow: str = "SignfinderYellow"
    folder_red: str = "SignfinderRed"
    folder_archive: str = "SignfinderArchive"
    # OAuth2 / XOAUTH2
    auth_method: str = "basic"          # "basic" | "xoauth2"
    oauth2_provider: str = ""           # google | microsoft | yandex | mailru | rambler
    oauth2_client_id: str = ""
    oauth2_client_secret: str = ""
    oauth2_refresh_token: str = ""
    oauth2_token_endpoint: str = ""     # override; иначе берётся из пресета провайдера
