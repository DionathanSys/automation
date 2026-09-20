from __future__ import annotations

from datetime import UTC, datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from automation.config import settings
from automation.db.automation_repository import AutomationRepository
from automation.jobs.registry import JOB_REGISTRY
from automation.jobs.service import JobService
from automation.services.collector import CollectorService
from automation.utils.logger import get_logger


logger = get_logger(__name__)


def start_scheduler(collector: CollectorService, timezone: str) -> None:
    scheduler = BlockingScheduler(timezone=timezone)

    for job in JOB_REGISTRY:
        if not job.enabled or not job.schedule_cron:
            continue

        scheduler.add_job(
            collector.run_job,
            CronTrigger.from_crontab(job.schedule_cron, timezone=timezone),
            kwargs={
                "site_name": job.site_name,
                "report_name": job.report_name,
                "filters": job.filters,
            },
            id=f"{job.site_name}:{job.report_name}",
            replace_existing=True,
        )
        logger.info("Job agendado: %s/%s", job.site_name, job.report_name)

    scheduler.start()


def start_automation_scheduler(repository: AutomationRepository) -> None:
    """Enqueue scheduled jobs through JobService instead of running Playwright."""
    repository.ensure_schema()
    client_code = settings.automation.client_id.strip()
    client = repository.get_client(client_code)
    if client is None:
        raise RuntimeError("AUTOMATION_CLIENT_ID nao possui cliente cadastrado.")

    service = JobService(repository, enqueue=_enqueue_job)
    scheduler = BlockingScheduler(timezone=settings.app.timezone)

    interval_jobs = [
        (
            "site_alpha_monitoring_trips",
            settings.monitoring_trips.poll_enabled,
            settings.monitoring_trips.poll_interval_seconds,
        ),
        (
            "site_alpha_daily_trip_summary",
            settings.daily_trip_summary.poll_enabled,
            settings.daily_trip_summary.poll_interval_seconds,
        ),
        (
            "site_alpha_closed_trips",
            settings.closed_trips.poll_enabled,
            settings.closed_trips.poll_interval_seconds,
        ),
    ]

    for collector_name, enabled, interval_seconds in interval_jobs:
        if not enabled:
            continue

        scheduler.add_job(
            _submit_scheduled_job,
            "interval",
            seconds=interval_seconds,
            kwargs={
                "service": service,
                "client": client,
                "collector_name": collector_name,
                "interval_seconds": interval_seconds,
            },
            id=f"automation:{collector_name}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Job de automacao agendado: %s", collector_name)

    scheduler.start()


def _submit_scheduled_job(
    service: JobService,
    client: dict,
    collector_name: str,
    interval_seconds: int,
) -> None:
    now_timestamp = datetime.now(UTC).timestamp()
    scheduled_timestamp = int(now_timestamp // interval_seconds) * interval_seconds
    scheduled_at = datetime.fromtimestamp(scheduled_timestamp, UTC)
    key = f"schedule:{collector_name}:{scheduled_at.isoformat()}"
    service.create_job(
        client=client,
        collector_name=collector_name,
        parameters={},
        requested_by="scheduler",
        metadata={"scheduled_at": scheduled_at.isoformat()},
        idempotency_key=key,
    )


def _enqueue_job(job_id: str) -> None:
    from automation.jobs.worker import enqueue_job

    enqueue_job(job_id)
