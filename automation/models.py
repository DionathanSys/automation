from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportColumn:
    name: str
    data_type: str = "string"
    nullable: bool = True
    length: int | None = None


@dataclass(frozen=True)
class ReportDefinition:
    site_name: str
    report_name: str
    table_name: str
    columns: list[ReportColumn]
    unique_keys: list[str]
    description: str = ""


@dataclass(frozen=True)
class HtmlTableSelectors:
    report_path: str
    table: str
    header_cells: str = "thead tr th"
    row_selector: str = "tbody tr"
    next_page: str | None = None
    loading_indicator: str | None = None
    empty_state: str | None = None
