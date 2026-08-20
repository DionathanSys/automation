from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from playwright.sync_api import BrowserContext, Locator, Page

from automation.models import HtmlTableSelectors


class BaseSite(ABC):
    site_name: str

    def __init__(self, context: BrowserContext) -> None:
        self.context = context
        self.page: Page = context.new_page()

    @abstractmethod
    def login(self) -> None:
        """Autentica no site."""

    @abstractmethod
    def open_report(self, report_name: str, filters: dict[str, Any]) -> None:
        """Abre o relatorio e aplica filtros."""

    @abstractmethod
    def extract_current_page(self, report_name: str) -> list[dict[str, Any]]:
        """Extrai as linhas visiveis da pagina atual."""

    @abstractmethod
    def go_to_next_page(self, report_name: str) -> bool:
        """Avanca para a proxima pagina. Retorna False se nao houver mais paginas."""

    def close(self) -> None:
        self.page.close()


class BaseHtmlTableSite(BaseSite):
    base_url: str = ""
    report_selectors: dict[str, HtmlTableSelectors] = {}

    def open_report(self, report_name: str, filters: dict[str, Any]) -> None:
        selectors = self.get_report_selectors(report_name)
        self.page.goto(f"{self.base_url}{selectors.report_path}")
        self.apply_filters(report_name, filters)
        self.wait_until_report_ready(report_name)

    def extract_current_page(self, report_name: str) -> list[dict[str, Any]]:
        selectors = self.get_report_selectors(report_name)
        table = self.page.locator(selectors.table)
        headers = self._extract_headers(table, selectors)
        rows: list[dict[str, Any]] = []

        for row_locator in table.locator(selectors.row_selector).all():
            values = [cell.inner_text().strip() for cell in row_locator.locator("td").all()]
            if not any(values):
                continue
            rows.append(dict(zip(headers, values, strict=False)))

        return self.transform_rows(report_name, rows)

    def go_to_next_page(self, report_name: str) -> bool:
        selectors = self.get_report_selectors(report_name)
        if not selectors.next_page:
            return False

        next_button = self.page.locator(selectors.next_page)
        if next_button.count() == 0 or not next_button.is_enabled():
            return False

        next_button.click()
        self.wait_until_report_ready(report_name)
        return True

    def apply_filters(self, report_name: str, filters: dict[str, Any]) -> None:
        """Sobrescreva quando o relatorio precisar interagir com filtros."""

    def wait_until_report_ready(self, report_name: str) -> None:
        selectors = self.get_report_selectors(report_name)
        self.page.locator(selectors.table).wait_for(state="visible")

        if selectors.loading_indicator:
            loading = self.page.locator(selectors.loading_indicator)
            if loading.count() > 0:
                loading.last.wait_for(state="hidden")

    def transform_rows(self, report_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows

    def get_report_selectors(self, report_name: str) -> HtmlTableSelectors:
        if report_name not in self.report_selectors:
            raise ValueError(f"Seletores nao cadastrados para {self.site_name}/{report_name}")
        return self.report_selectors[report_name]

    def _extract_headers(self, table: Locator, selectors: HtmlTableSelectors) -> list[str]:
        headers = [cell.inner_text().strip() for cell in table.locator(selectors.header_cells).all()]
        return [self.normalize_header_name(header, index) for index, header in enumerate(headers, start=1)]

    def normalize_header_name(self, header: str, index: int) -> str:
        normalized = "_".join(header.lower().split())
        return normalized or f"column_{index}"
