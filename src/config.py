from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT_DIR / ".env")


def _bool_env(name: str, default: bool) -> bool:
    value = _config_value(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _config_value(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        import streamlit as st

        secret_value = st.secrets.get(name, None)
        if secret_value is not None:
            return str(secret_value)
    except Exception:
        pass
    return default


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_source: str
    tushare_token: str
    remote_db_url: str
    wencai_user_data_dir: Path
    wencai_headless: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_to: tuple[str, ...]


def get_settings() -> Settings:
    _load_env()
    db_path = Path(_config_value("APP_DB_PATH", "stock_strategy.sqlite3") or "stock_strategy.sqlite3")
    if not db_path.is_absolute():
        db_path = ROOT_DIR / db_path

    user_data_dir = Path(_config_value("WENCAI_USER_DATA_DIR", ".wencai_browser") or ".wencai_browser")
    if not user_data_dir.is_absolute():
        user_data_dir = ROOT_DIR / user_data_dir

    recipients = tuple(
        item.strip()
        for item in (_config_value("SMTP_TO", "") or "").replace(";", ",").split(",")
        if item.strip()
    )

    return Settings(
        db_path=db_path,
        data_source=(_config_value("APP_DATA_SOURCE", "akshare") or "akshare").strip().lower(),
        tushare_token=(_config_value("TUSHARE_TOKEN", "") or "").strip(),
        remote_db_url=(_config_value(
            "APP_REMOTE_DB_URL",
            "https://raw.githubusercontent.com/samcoolpop/stock-strategy-dashboard/main/stock_strategy.sqlite3",
        ) or "").strip(),
        wencai_user_data_dir=user_data_dir,
        wencai_headless=_bool_env("WENCAI_HEADLESS", False),
        smtp_host=(_config_value("SMTP_HOST", "") or "").strip(),
        smtp_port=int(_config_value("SMTP_PORT", "465") or "465"),
        smtp_user=(_config_value("SMTP_USER", "") or "").strip(),
        smtp_password=_config_value("SMTP_PASSWORD", "") or "",
        smtp_from=(_config_value("SMTP_FROM", "") or "").strip(),
        smtp_to=recipients,
    )
