from __future__ import annotations

from datetime import datetime
from typing import Any

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from automation.config import settings
from automation.db.connection import create_mysql_engine
from automation.db.repository import MySQLRepository
from automation.jobs.interval import register_interval_job
from automation.reports import REPORT_REGISTRY
from automation.services.collector import CollectorService


MONITORING_TRIPS_DEFINITION = REPORT_REGISTRY[("site_alpha", "monitoring_trips")]
DAILY_TRIP_SUMMARY_DEFINITION = REPORT_REGISTRY[("site_alpha", "daily_trip_summary")]


def create_app() -> FastAPI:
    repository = MySQLRepository(create_mysql_engine())
    collector = CollectorService(repository)

    app = FastAPI(title="Automation API", version="1.0.0")

    @app.on_event("startup")
    def on_startup() -> None:
        interval_jobs = _get_enabled_interval_jobs()
        if not interval_jobs:
            return

        scheduler = BackgroundScheduler(timezone=settings.app.timezone)
        for site_name, report_name, interval_seconds in interval_jobs:
            collector.run_job(site_name, report_name, {})
            register_interval_job(
                scheduler,
                collector,
                settings.app.timezone,
                interval_seconds,
                site_name,
                report_name,
            )
        scheduler.start()
        app.state.scheduler = scheduler

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            scheduler.shutdown(wait=False)

    @app.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/site-alpha/monitoring-trips")
    def list_monitoring_trips(_: None = Depends(_require_api_key)) -> list[dict[str, Any]]:
        rows = repository.fetch_report_rows(MONITORING_TRIPS_DEFINITION, order_by="plate")
        return [_serialize_row(row, _monitoring_trip_fields()) for row in rows]

    @app.get("/api/site-alpha/daily-trip-summaries")
    def list_daily_trip_summaries(
        report_date: str | None = Query(default=None),
        _: None = Depends(_require_api_key),
    ) -> list[dict[str, Any]]:
        filters = {"report_date": report_date or _today_date_string()}
        rows = repository.fetch_report_rows(DAILY_TRIP_SUMMARY_DEFINITION, order_by="plate", filters=filters)
        return [_serialize_row(row, _daily_trip_summary_fields()) for row in rows]

    return app


def run_api() -> None:
    uvicorn.run(
        "automation.api:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
    )


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api.api_key:
        return

    if x_api_key != settings.api.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")


def _serialize_row(row: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if key not in allowed_keys:
            continue
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    return payload


def _monitoring_trip_fields() -> set[str]:
    return {
        "plate",
        "started_at",
        "current_location",
        "status",
        "weight",
        "destination",
        "collected_at",
    }


def _daily_trip_summary_fields() -> set[str]:
    return {
        "report_date",
        "plate",
        "fleet",
        "vehicle_id",
        "completed_trip_count",
        "total_suggested_km",
        "total_driven_km",
        "collected_at",
    }


def _get_enabled_interval_jobs() -> list[tuple[str, str, int]]:
    jobs: list[tuple[str, str, int]] = []
    if settings.monitoring_trips.poll_enabled:
        jobs.append(("site_alpha", "monitoring_trips", settings.monitoring_trips.poll_interval_seconds))
    if settings.daily_trip_summary.poll_enabled:
        jobs.append(("site_alpha", "daily_trip_summary", settings.daily_trip_summary.poll_interval_seconds))
    return jobs


def _today_date_string() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(settings.app.timezone)).strftime("%d/%m/%Y")
