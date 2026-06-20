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
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


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
    db_path = Path(os.getenv("APP_DB_PATH", "stock_strategy.sqlite3"))
    if not db_path.is_absolute():
        db_path = ROOT_DIR / db_path

    user_data_dir = Path(os.getenv("WENCAI_USER_DATA_DIR", ".wencai_browser"))
    if not user_data_dir.is_absolute():
        user_data_dir = ROOT_DIR / user_data_dir

    recipients = tuple(
        item.strip()
        for item in os.getenv("SMTP_TO", "").replace(";", ",").split(",")
        if item.strip()
    )

    return Settings(
        db_path=db_path,
        data_source=os.getenv("APP_DATA_SOURCE", "akshare").strip().lower(),
        tushare_token=os.getenv("TUSHARE_TOKEN", "").strip(),
        remote_db_url=os.getenv(
            "APP_REMOTE_DB_URL",
            "https://raw.githubusercontent.com/samcoolpop/stock-strategy-dashboard/main/stock_strategy.sqlite3",
        ).strip(),
        wencai_user_data_dir=user_data_dir,
        wencai_headless=_bool_env("WENCAI_HEADLESS", False),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_to=recipients,
    )
