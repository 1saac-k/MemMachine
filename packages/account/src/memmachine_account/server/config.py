"""Config file loading for memmachine-account-server (DESIGN.md §10)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = "~/.config/memmachine-account/config.yml"
CONFIG_PATH_ENV_VAR = "MEMMACHINE_ACCOUNT_CONFIG"


class ServerSection(BaseModel):
    """`server:` section."""

    host: str = "0.0.0.0"
    port: int = 8090
    workers: int = 1


class LoggingSection(BaseModel):
    """`logging:` section."""

    level: str = "info"
    format: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


class UpstreamSection(BaseModel):
    """`memmachine_upstream:` section."""

    base_url: str
    timeout_seconds: float = 30


class StorageSection(BaseModel):
    """`storage:` section."""

    sqlite_path: str


class AuthSection(BaseModel):
    """`auth:` section."""

    allowed_email_domains: list[str]
    seed_admins: list[str] = Field(default_factory=list)
    password_min_length: int = 8
    failed_login_lockout_threshold: int = 5
    email_code_length: int = 6
    email_code_expiry_minutes: int = 30


class SmtpSection(BaseModel):
    """`smtp:` section."""

    host: str
    port: int = 587
    username: str
    password: str
    from_address: str
    encryption: Literal["starttls", "ssl", "none"] = "starttls"
    timeout_seconds: float = 10


class AppConfig(BaseModel):
    """Root config model for memmachine-account-server."""

    server: ServerSection = Field(default_factory=ServerSection)
    logging: LoggingSection = Field(default_factory=LoggingSection)
    memmachine_upstream: UpstreamSection
    storage: StorageSection
    auth: AuthSection
    smtp: SmtpSection


def resolve_config_path(explicit_path: str | None = None) -> Path:
    """Resolve the config file path from an explicit arg, env var, or default."""
    raw_path = explicit_path or os.environ.get(CONFIG_PATH_ENV_VAR) or DEFAULT_CONFIG_PATH
    return Path(raw_path).expanduser()


def load_config(explicit_path: str | None = None) -> AppConfig:
    """Load and validate the YAML config file (DESIGN.md §10)."""
    path = resolve_config_path(explicit_path)
    with path.open() as config_file:
        raw = yaml.safe_load(config_file)
    return AppConfig.model_validate(raw)
