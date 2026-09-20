from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import URL


load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class AppConfig:
    app_env: str = os.getenv("APP_ENV", "development")
    headless: bool = _get_bool("HEADLESS", True)
    slow_mo_ms: int = _get_int("SLOW_MO_MS", 0)
    default_timeout_ms: int = _get_int("DEFAULT_TIMEOUT_MS", 30000)
    timezone: str = os.getenv("TIMEZONE", "America/Sao_Paulo")


@dataclass(frozen=True)
class MySQLConfig:
    host: str = os.getenv("MYSQL_HOST", "localhost")
    port: int = _get_int("MYSQL_PORT", 3306)
    database: str = os.getenv("MYSQL_DATABASE", "automation")
    user: str = os.getenv("MYSQL_USER", "root")
    password: str = os.getenv("MYSQL_PASSWORD", "")

    @property
    def sqlalchemy_url(self) -> str:
        return URL.create(
            "mysql+mysqlconnector",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        ).render_as_string(hide_password=False)


@dataclass(frozen=True)
class SiteSoftlogConfig:
    base_url: str = os.getenv("SITE_SOFTLOG_BASE_URL", "https://app.softlogbrasil.com.br")
    username: str = os.getenv("SITE_SOFTLOG_USERNAME", "")
    password: str = os.getenv("SITE_SOFTLOG_PASSWORD", "")


@dataclass(frozen=True)
class SiteSascarConfig:
    base_url: str = os.getenv("SITE_SASCAR_BASE_URL", "https://telemetria.sascar.com.br")
    usuario: str = os.getenv("SITE_SASCAR_USUARIO", "")
    login: str = os.getenv("SITE_SASCAR_LOGIN", "")
    password: str = os.getenv("SITE_SASCAR_PASSWORD", "")
    filial_veiculo: str = os.getenv("SITE_SASCAR_FILIAL_VEICULO", "MATRIZ")
    window_hours: int = _get_int("SASCAR_WINDOW_HOURS", 24)


@dataclass(frozen=True)
class ApiConfig:
    host: str = os.getenv("API_HOST", "0.0.0.0")
    port: int = _get_int("API_PORT", 8000)


@dataclass(frozen=True)
class QueueConfig:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue_name: str = os.getenv("AUTOMATION_QUEUE_NAME", "automation")
    worker_id: str = os.getenv("AUTOMATION_WORKER_ID", "automation-worker-1")


@dataclass(frozen=True)
class AutomationConfig:
    client_id: str = os.getenv("AUTOMATION_CLIENT_ID", "")
    client_secret: str = os.getenv("AUTOMATION_CLIENT_SECRET", "")
    previous_client_secret: str = os.getenv("AUTOMATION_CLIENT_SECRET_PREVIOUS", "")
    callback_url: str = os.getenv("AUTOMATION_CALLBACK_URL", "")
    webhook_client_id: str = os.getenv("AUTOMATION_WEBHOOK_CLIENT_ID", "automation_prod")
    webhook_secret: str = os.getenv("AUTOMATION_WEBHOOK_SECRET", "")
    previous_webhook_secret: str = os.getenv("AUTOMATION_WEBHOOK_SECRET_PREVIOUS", "")
    webhook_timeout_seconds: int = _get_int("AUTOMATION_WEBHOOK_TIMEOUT_SECONDS", 30)
    hmac_timestamp_tolerance_seconds: int = _get_int(
        "AUTOMATION_HMAC_TIMESTAMP_TOLERANCE_SECONDS", 300
    )
    nonce_ttl_seconds: int = _get_int("AUTOMATION_NONCE_TTL_SECONDS", 600)
    max_result_page_size: int = _get_int("AUTOMATION_MAX_RESULT_PAGE_SIZE", 500)
    default_max_attempts: int = _get_int("AUTOMATION_DEFAULT_MAX_ATTEMPTS", 3)


@dataclass(frozen=True)
class Settings:
    app: AppConfig = AppConfig()
    mysql: MySQLConfig = MySQLConfig()
    site_softlog: SiteSoftlogConfig = SiteSoftlogConfig()
    sascar: SiteSascarConfig = SiteSascarConfig()
    api: ApiConfig = ApiConfig()
    queue: QueueConfig = QueueConfig()
    automation: AutomationConfig = AutomationConfig()


settings = Settings()
