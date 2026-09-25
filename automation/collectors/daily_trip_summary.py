from __future__ import annotations

from datetime import date, datetime
from typing import Any

from automation.collectors.site_alpha_closed_trips import SiteAlphaClosedTripsCollector


class DailyTripSummaryCollector:
    """Adapts closed Softlog trips to the Laravel daily-trip contract."""

    def collect(
        self,
        report_date: date,
        progress_callback=None,
        cancellation_check=None,
    ) -> list[dict[str, Any]]:
        rows = SiteAlphaClosedTripsCollector().collect(
            report_date,
            report_date,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )
        return [self._normalize_row(row) for row in rows]

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        ended_at = row.get("ended_at")
        started_at = row.get("started_at")
        destination = row.get("destination")
        customer = row.get("customer") or destination
        drivers = [
            driver
            for driver in (row.get("driver_1"), row.get("driver_2"))
            if driver
        ]

        return {
            "external_id": row["external_id"],
            "numero_viagem": row["trip_number"],
            "placa": row.get("plate"),
            "cliente": customer,
            "destino": destination,
            "km_rodado": row.get("driven_km"),
            "km_pago": row.get("suggested_km"),
            "data_competencia": _format_date(ended_at),
            "data_inicio": _format_datetime(started_at),
            "data_fim": _format_datetime(ended_at),
            "possui_pendencia": False,
            "pendencias": [],
            "motoristas": drivers,
        }


def _format_date(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    return value.strftime("%Y-%m-%d")


def _format_datetime(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")
