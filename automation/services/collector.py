from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from playwright.sync_api import sync_playwright

from automation.config import settings
from automation.db.repository import MySQLRepository
from automation.models import JobRunResult
from automation.reports import REPORT_REGISTRY
from automation.sites import SITE_REGISTRY
from automation.utils.logger import get_logger


logger = get_logger(__name__)


class CollectorService:
    def __init__(self, repository: MySQLRepository) -> None:
        self.repository = repository

    def list_registered_jobs(self) -> list[tuple[str, str]]:
        return sorted(REPORT_REGISTRY.keys())

    def collect_rows(
        self,
        site_name: str,
        report_name: str,
        filters: dict | None = None,
        progress_callback=None,
        cancellation_check=None,
    ) -> list[dict]:
        """Collect normalized rows without writing to the legacy report tables."""
        filters = filters or {}
        report_key = (site_name, report_name)
        if report_key not in REPORT_REGISTRY:
            raise ValueError(f"Relatorio nao registrado: {site_name}/{report_name}")
        if site_name not in SITE_REGISTRY:
            raise ValueError(f"Site nao registrado: {site_name}")

        report_definition = REPORT_REGISTRY[report_key]
        collected_rows: list[dict] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=settings.app.headless,
                slow_mo=settings.app.slow_mo_ms,
            )
            context = browser.new_context(locale="pt-BR")
            context.set_default_timeout(settings.app.default_timeout_ms)
            site_class = SITE_REGISTRY[site_name]
            site = site_class(context)

            try:
                site.login()
                site.open_report(report_name, filters)
                page_number = 0
                while True:
                    if cancellation_check and cancellation_check():
                        raise CollectorCancelled()

                    rows = site.extract_current_page(report_name)
                    normalized_rows = [
                        {column.name: row.get(column.name) for column in report_definition.columns}
                        for row in rows
                    ]
                    collected_rows.extend(normalized_rows)
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

    def run_job(self, site_name: str, report_name: str, filters: dict | None = None) -> JobRunResult:
        filters = filters or {}
        report_key = (site_name, report_name)
        if report_key not in REPORT_REGISTRY:
            raise ValueError(f"Relatorio nao registrado: {site_name}/{report_name}")
        if site_name not in SITE_REGISTRY:
            raise ValueError(f"Site nao registrado: {site_name}")

        report_definition = REPORT_REGISTRY[report_key]
        run_id = str(uuid4())
        started_at = datetime.utcnow()
        result = JobRunResult(
            site_name=site_name,
            report_name=report_name,
            started_at=started_at,
            finished_at=started_at,
        )

        logger.info("Iniciando coleta de %s/%s", site_name, report_name)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=settings.app.headless,
                    slow_mo=settings.app.slow_mo_ms,
                )
                context = browser.new_context(locale="pt-BR")
                context.set_default_timeout(settings.app.default_timeout_ms)

                site_class = SITE_REGISTRY[site_name]
                site = site_class(context)

                try:
                    site.login()
                    site.open_report(report_name, filters)

                    while True:
                        rows = site.extract_current_page(report_name)
                        normalized_rows = [
                            {column.name: row.get(column.name) for column in report_definition.columns}
                            for row in rows
                        ]
                        inserted_count, updated_count = self.repository.upsert_rows(
                            report_definition,
                            normalized_rows,
                        )
                        result.pages_processed += 1
                        result.rows_processed += len(normalized_rows)
                        result.inserted_count += inserted_count
                        result.updated_count += updated_count

                        if not site.go_to_next_page(report_name):
                            break
                finally:
                    site.close()
                    context.close()
                    browser.close()
        except Exception as exc:
            result.status = "error"
            result.error_message = str(exc)
            logger.exception("Falha na coleta de %s/%s", site_name, report_name)

        result.finished_at = datetime.utcnow()
        self.repository.save_job_run(run_id, result, filters)
        return result


class CollectorCancelled(Exception):
    """Raised when a collector observes a cooperative cancellation request."""
