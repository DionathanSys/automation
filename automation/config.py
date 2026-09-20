from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


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
        return (
            f"mysql+mysqlconnector://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass(frozen=True)
class SiteAlphaConfig:
    base_url: str = os.getenv("SITE_ALPHA_BASE_URL", "https://app.softlogbrasil.com.br")
    username: str = os.getenv("SITE_ALPHA_USERNAME", "")
    password: str = os.getenv("SITE_ALPHA_PASSWORD", "")


@dataclass(frozen=True)
class SiteSascarConfig:
    base_url: str = os.getenv("SITE_SASCAR_BASE_URL", "https://telemetria.sascar.com.br")
    usuario: str = os.getenv("SITE_SASCAR_USUARIO", "")
    login: str = os.getenv("SITE_SASCAR_LOGIN", "")
    password: str = os.getenv("SITE_SASCAR_PASSWORD", "")
    filial_veiculo: str = os.getenv("SITE_SASCAR_FILIAL_VEICULO", "MATRIZ")
    window_hours: int = _get_int("SASCAR_WINDOW_HOURS", 24)


@dataclass(frozen=True)
class MonitoringTripsConfig:
    poll_enabled: bool = _get_bool("MONITORING_TRIPS_POLL_ENABLED", False)
    poll_interval_seconds: int = _get_int("MONITORING_TRIPS_POLL_INTERVAL_SECONDS", 600)


@dataclass(frozen=True)
class DailyTripSummaryConfig:
    poll_enabled: bool = _get_bool("DAILY_TRIP_SUMMARY_POLL_ENABLED", False)
    poll_interval_seconds: int = _get_int("DAILY_TRIP_SUMMARY_POLL_INTERVAL_SECONDS", 300)


@dataclass(frozen=True)
class ClosedTripsConfig:
    poll_enabled: bool = _get_bool("CLOSED_TRIPS_POLL_ENABLED", False)
    poll_interval_seconds: int = _get_int("CLOSED_TRIPS_POLL_INTERVAL_SECONDS", 900)


@dataclass(frozen=True)
class ApiConfig:
    host: str = os.getenv("API_HOST", "0.0.0.0")
    port: int = _get_int("API_PORT", 8000)
    api_key: str = os.getenv("API_KEY", "")


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
    hmac_timestamp_tolerance_seconds: int = _get_int(
        "AUTOMATION_HMAC_TIMESTAMP_TOLERANCE_SECONDS", 300
    )
    nonce_ttl_seconds: int = _get_int("AUTOMATION_NONCE_TTL_SECONDS", 600)
    max_result_page_size: int = _get_int("AUTOMATION_MAX_RESULT_PAGE_SIZE", 500)
    default_max_attempts: int = _get_int("AUTOMATION_DEFAULT_MAX_ATTEMPTS", 3)


@dataclass(frozen=True)
class StateStoreConfig:
    sqlite_path: str = os.getenv("STATE_SQLITE_PATH", "automation_state.sqlite3")


@dataclass(frozen=True)
class ReceiverConfig:
    base_url: str = os.getenv("RECEIVER_BASE_URL", "https://app.axionsoft.com.br")
    api_key: str = os.getenv("RECEIVER_API_KEY", "")
    viagem_atual_path: str = os.getenv("RECEIVER_VIAGEM_ATUAL_PATH", "/api/integracoes/viagem-atual")
    closed_trips_path: str = os.getenv("RECEIVER_CLOSED_TRIPS_PATH", "/api/integracoes/viagens")
    movimento_diario_path: str = os.getenv(
        "RECEIVER_MOVIMENTO_DIARIO_PATH", "/api/integracoes/movimento-diario"
    )
    historico_quilometragem_path: str = os.getenv(
        "RECEIVER_HISTORICO_QUILOMETRAGEM_PATH", "/api/integracoes/historico-quilometragem"
    )
    webhook_secret: str = os.getenv("RECEIVER_WEBHOOK_SECRET", "")
    timeout_seconds: int = _get_int("RECEIVER_TIMEOUT_SECONDS", 30)
    closed_trips_cutoff_date: str = os.getenv("CLOSED_TRIPS_CUTOFF_DATE", "")
    closed_trips_batch_size: int = _get_int("CLOSED_TRIPS_BATCH_SIZE", 100)
    default_business_unit: str = os.getenv("RECEIVER_DEFAULT_BUSINESS_UNIT", "CHAPECO")
    default_customer: str = os.getenv("RECEIVER_DEFAULT_CUSTOMER", "BRF S.A. CHAPECO/SC")


@dataclass(frozen=True)
class Settings:
    app: AppConfig = AppConfig()
    mysql: MySQLConfig = MySQLConfig()
    site_alpha: SiteAlphaConfig = SiteAlphaConfig()
    sascar: SiteSascarConfig = SiteSascarConfig()
    monitoring_trips: MonitoringTripsConfig = MonitoringTripsConfig()
    daily_trip_summary: DailyTripSummaryConfig = DailyTripSummaryConfig()
    closed_trips: ClosedTripsConfig = ClosedTripsConfig()
    api: ApiConfig = ApiConfig()
    queue: QueueConfig = QueueConfig()
    automation: AutomationConfig = AutomationConfig()
    state_store: StateStoreConfig = StateStoreConfig()
    receiver: ReceiverConfig = ReceiverConfig()


settings = Settings()
