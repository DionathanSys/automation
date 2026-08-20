from automation.config import settings
from automation.models import JobDefinition


JOB_REGISTRY: list[JobDefinition] = [
    JobDefinition(
        site_name="site_alpha",
        report_name="financial_summary",
        filters={},
        enabled=False,
        schedule_cron=None,
    ),
    JobDefinition(
        site_name="site_alpha",
        report_name="open_titles",
        filters={},
        enabled=False,
        schedule_cron=None,
    ),
    JobDefinition(
        site_name="site_beta",
        report_name="sales_by_day",
        filters={},
        enabled=False,
        schedule_cron=None,
    ),
    JobDefinition(
        site_name="site_beta",
        report_name="inventory_position",
        filters={},
        enabled=False,
        schedule_cron=None,
    ),
    JobDefinition(
        site_name="site_alpha",
        report_name="monitoring_trips",
        filters={},
        enabled=settings.monitoring_trips.poll_enabled,
        schedule_cron=None,
    ),
    JobDefinition(
        site_name="site_alpha",
        report_name="daily_trip_summary",
        filters={},
        enabled=settings.daily_trip_summary.poll_enabled,
        schedule_cron=None,
    )
]
