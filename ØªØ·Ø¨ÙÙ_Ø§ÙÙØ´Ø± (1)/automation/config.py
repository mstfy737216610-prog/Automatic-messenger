from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """إعدادات البيئة؛ الأسرار هنا فقط ولا تُحفظ في قاعدة البيانات."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "مرسال"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path | None = None
    log_level: str = "INFO"

    ai_api_key: SecretStr | None = None
    ai_base_url: str = "https://api.hcnsec.cn/v1"
    ai_model: str = "auto"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2

    chromium_path: str | None = None
    playwright_headless: bool = True
    chromium_no_sandbox: bool = True
    scheduler_enabled: bool = True
    scheduler_poll_seconds: float = 2.0
    worker_poll_seconds: float = 1.0

    dry_run: bool = True
    publishing_enabled: bool = False
    max_download_mb: int = 250
    media_retention_days: int = 90
    log_retention_days: int = 90
    auto_cleanup: bool = True

    web_username: str | None = None
    web_password: SecretStr | None = None

    @field_validator("ai_base_url")
    @classmethod
    def normalize_ai_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        for suffix in ("/models", "/chat/completions"):
            value = value.removesuffix(suffix)
        return value.rstrip("/")

    @field_validator("data_dir", mode="before")
    @classmethod
    def expand_data_dir(cls, value: object) -> object:
        return Path(str(value)).expanduser() if value is not None else value

    @property
    def database_path(self) -> Path:
        return self.db_path or self.data_dir / "bot_memory.db"

    @property
    def chromium_executable(self) -> str | None:
        if self.chromium_path:
            return str(Path(self.chromium_path).expanduser())
        return shutil.which("chromium-browser") or shutil.which("chromium") or shutil.which("google-chrome")

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("accounts", "backups", "tmp", "exports"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

    def public_ai_config(self) -> dict[str, object]:
        return {
            "base_url": self.ai_base_url,
            "model": self.ai_model,
            "timeout_seconds": self.ai_timeout_seconds,
            "key_configured": bool(self.ai_api_key and self.ai_api_key.get_secret_value()),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def mask_proxy(value: str | None) -> str | None:
    """يعرض عنوان البروكسي دون كلمة المرور، ولا يُستخدم للاتصال."""
    if not value:
        return None
    try:
        parts = urlsplit(value if "://" in value else f"http://{value}")
        host = parts.hostname or ""
        if not host:
            return "••••"
        port = f":{parts.port}" if parts.port else ""
        user = f"{parts.username}:***@" if parts.username else ""
        return urlunsplit((parts.scheme, f"{user}{host}{port}", "", "", ""))
    except (ValueError, TypeError):
        return "••••"
