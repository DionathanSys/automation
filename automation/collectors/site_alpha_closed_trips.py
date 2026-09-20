from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from automation.config import settings
from automation.services.collector import CollectorCancelled
from automation.sites import SITE_REGISTRY


SEARCH_OVERLAP_DAYS = 2


class SiteAlphaClosedTripsCollector:
    def collect(
        self,
        start_date: date,
        end_date: date,
        progress_callback=None,
        cancellation_check=None,
    ) -> list[dict[str, Any]]:
        if end_date < start_date:
            raise ValueError("A data final deve ser maior ou igual a data inicial.")

        search_start_date = start_date - timedelta(days=SEARCH_OVERLAP_DAYS)

        with self._site_session() as site:
            if cancellation_check and cancellation_check():
                raise CollectorCancelled()

            site.open_report(
                "closed_trips",
                {
                    "start_date": search_start_date.strftime("%d/%m/%Y"),
                    "end_date": end_date.strftime("%d/%m/%Y"),
                },
            )
            rows = self._filter_rows(
                site.extract_current_page("closed_trips"),
                start_date,
                end_date,
            )
            collected_rows = [
                self._normalize_row(row) for row in rows
            ]
            if progress_callback:
                progress_callback(1, 1, "Periodo de viagens encerradas coletado")

        return collected_rows

    def _site_session(self):
        return _SiteAlphaSession()

    @staticmethod
    def _filter_rows(
        rows: list[dict[str, Any]],
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        valid_rows = [
            row
            for row in rows
            if isinstance(row.get("ended_at"), datetime)
            and start_date <= row["ended_at"].date() <= end_date
        ]
        return sorted(valid_rows, key=lambda row: int(row["trip_number"]))

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        trip_number = str(row["trip_number"])
        ended_at = row["ended_at"]
        return {
            "external_id": f"site_alpha:closed_trip:{trip_number}",
            "trip_number": trip_number,
            "plate": self._clean(row.get("plate")),
            "vehicle_id": row.get("vehicle_id"),
            "fleet": self._clean(row.get("fleet")),
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "suggested_km": row.get("suggested_km"),
            "driven_km": row.get("driven_km"),
            "destination": self._clean(row.get("cliente")),
            "cargo_reference": self._clean(row.get("carga_cliente")),
            "driver_1": self._clean(row.get("motorista1")),
            "driver_2": self._clean(row.get("motorista2")),
            "report_date": ended_at.strftime("%d/%m/%Y"),
            "collected_at": datetime.now(ZoneInfo(settings.app.timezone)),
        }

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class _SiteAlphaSession:
    def __enter__(self):
        self.site = None
        self._context = None
        self._browser = None
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=settings.app.headless,
            slow_mo=settings.app.slow_mo_ms,
        )
        self._context = self._browser.new_context(locale="pt-BR")
        self._context.set_default_timeout(settings.app.default_timeout_ms)
        self.site = SITE_REGISTRY["site_alpha"](self._context)
        self.site.login()
        return self.site

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.site is not None:
            self.site.close()
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        self._playwright.stop()
