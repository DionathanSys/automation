from __future__ import annotations

from typing import Any

from playwright.sync_api import sync_playwright

from automation.config import settings
from automation.reports import REPORT_REGISTRY
from automation.sites import SITE_REGISTRY


class CollectorService:
    """Runs a registered source collector for a persisted API job."""

    def collect_rows(
        self,
        site_name: str,
        report_name: str,
        filters: dict[str, Any] | None = None,
        progress_callback=None,
        cancellation_check=None,
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        report_key = (site_name, report_name)
        if report_key not in REPORT_REGISTRY:
            raise ValueError(f"Relatorio nao registrado: {site_name}/{report_name}")
        if site_name not in SITE_REGISTRY:
            raise ValueError(f"Site nao registrado: {site_name}")

        report_definition = REPORT_REGISTRY[report_key]
        collected_rows: list[dict[str, Any]] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=settings.app.headless,
                slow_mo=settings.app.slow_mo_ms,
            )
            context = browser.new_context(locale="pt-BR")
            context.set_default_timeout(settings.app.default_timeout_ms)
            site = SITE_REGISTRY[site_name](context)

            try:
                site.login()
                site.open_report(report_name, filters)
                page_number = 0
                while True:
                    if cancellation_check and cancellation_check():
                        raise CollectorCancelled()

                    rows = site.extract_current_page(report_name)
                    collected_rows.extend(
                        {
                            column.name: row.get(column.name)
                            for column in report_definition.columns
                        }
                        for row in rows
                    )
                    page_number += 1
                    if progress_callback:
                        progress_callback(page_number, None, f"Pagina {page_number} coletada")
                    if not site.go_to_next_page(report_name):
                        break
            finally:
                site.close()
                context.close()
                browser.close()

        return collected_rows


class CollectorCancelled(Exception):
    """Raised when a collector observes a cooperative cancellation request."""
