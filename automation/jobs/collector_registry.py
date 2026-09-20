from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from automation.config import settings
from automation.services.collector import CollectorService
from automation.services.sascar_sync import SascarSyncService
from automation.services.site_alpha_sync import SiteAlphaSyncService


ProgressCallback = Callable[[int, int | None, str | None], None]
CancellationCheck = Callable[[], bool]
CollectorExecutor = Callable[
    [dict[str, Any], CollectorService, ProgressCallback, CancellationCheck],
    list[dict[str, Any]],
]


@dataclass(frozen=True)
class CollectorDefinition:
    name: str
    version: str
    schema_version: str
    max_concurrency: int
    execute: CollectorExecutor


def _execute_report(
    report_name: str,
    parameters: dict[str, Any],
    collector: CollectorService,
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> list[dict[str, Any]]:
    return collector.collect_rows(
        "site_alpha",
        report_name,
        parameters,
        progress_callback=progress,
        cancellation_check=is_cancelled,
    )


def _execute_monitoring_trips(
    parameters: dict[str, Any],
    collector: CollectorService,
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> list[dict[str, Any]]:
    return _execute_report("monitoring_trips", parameters, collector, progress, is_cancelled)


def _execute_daily_trip_summary(
    parameters: dict[str, Any],
    collector: CollectorService,
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> list[dict[str, Any]]:
    return _execute_report("daily_trip_summary", parameters, collector, progress, is_cancelled)


def _parse_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError("Data deve usar YYYY-MM-DD ou DD/MM/YYYY.")


def _execute_closed_trips(
    parameters: dict[str, Any],
    collector: CollectorService,
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> list[dict[str, Any]]:
    raw_start = str(parameters.get("from") or settings.receiver.closed_trips_cutoff_date)
    raw_end = str(
        parameters.get("to")
        or datetime.now(ZoneInfo(settings.app.timezone)).strftime("%Y-%m-%d")
    )
    if not raw_start:
        raise ValueError("Informe from ou configure CLOSED_TRIPS_CUTOFF_DATE.")
    service = SiteAlphaSyncService(state_repository=None, push_client=None)
    return service.collect_closed_trips(
        _parse_date(raw_start),
        _parse_date(raw_end),
        progress_callback=progress,
        cancellation_check=is_cancelled,
    )


def _execute_sascar_daily_movement(
    parameters: dict[str, Any],
    collector: CollectorService,
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> list[dict[str, Any]]:
    service = SascarSyncService(push_client=None)
    rows = service.push_daily_movement(
        dry_run=True,
        vehicle_limit=parameters.get("vehicle_limit"),
    )
    return [
        {
            "external_id": f"{row.get('veiculo')}:{row.get('dia')}",
            **row,
        }
        for row in rows
        if not is_cancelled()
    ]


def _execute_sascar_traveled_distance(
    parameters: dict[str, Any],
    collector: CollectorService,
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> list[dict[str, Any]]:
    service = SascarSyncService(push_client=None)
    batches = service.push_traveled_distance(dry_run=True)
    rows: list[dict[str, Any]] = []
    for batch in batches:
        for row in batch.get("registros", []):
            if is_cancelled():
                return rows
            rows.append(
                {
                    "external_id": f"{row.get('placa')}:{row.get('data_referencia')}",
                    **row,
                }
            )
    return rows


COLLECTOR_REGISTRY: dict[str, CollectorDefinition] = {
    "site_alpha_monitoring_trips": CollectorDefinition(
        name="site_alpha_monitoring_trips",
        version="1.0.0",
        schema_version="1.0",
        max_concurrency=1,
        execute=_execute_monitoring_trips,
    ),
    "site_alpha_daily_trip_summary": CollectorDefinition(
        name="site_alpha_daily_trip_summary",
        version="1.0.0",
        schema_version="1.0",
        max_concurrency=1,
        execute=_execute_daily_trip_summary,
    ),
    "site_alpha_closed_trips": CollectorDefinition(
        name="site_alpha_closed_trips",
        version="1.0.0",
        schema_version="1.0",
        max_concurrency=1,
        execute=_execute_closed_trips,
    ),
    "sascar_daily_movement": CollectorDefinition(
        name="sascar_daily_movement",
        version="1.0.0",
        schema_version="1.0",
        max_concurrency=1,
        execute=_execute_sascar_daily_movement,
    ),
    "sascar_traveled_distance": CollectorDefinition(
        name="sascar_traveled_distance",
        version="1.0.0",
        schema_version="1.0",
        max_concurrency=1,
        execute=_execute_sascar_traveled_distance,
    ),
}
