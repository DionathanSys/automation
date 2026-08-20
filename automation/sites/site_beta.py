from __future__ import annotations

from automation.models import HtmlTableSelectors
from automation.sites.base import BaseHtmlTableSite


class SiteBeta(BaseHtmlTableSite):
    site_name = "site_beta"
    base_url = "https://site-beta.example.com"
    report_selectors = {
        "sales_by_day": HtmlTableSelectors(
            report_path="/reports/sales-by-day",
            table="table",
            next_page="button.next-page",
            loading_indicator=".loading",
        ),
        "inventory_position": HtmlTableSelectors(
            report_path="/reports/inventory-position",
            table="table",
            next_page="button.next-page",
            loading_indicator=".loading",
        ),
    }

    def login(self) -> None:
        raise NotImplementedError("Implemente o login real do site_beta.")
