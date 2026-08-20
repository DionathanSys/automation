from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from automation.jobs.registry import JOB_REGISTRY
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
