from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.sql.type_api import TypeEngine


SQL_TYPE_MAP: dict[str, TypeEngine[Any]] = {
    "string": String(255),
    "text": Text(),
    "integer": Integer(),
    "float": Float(),
    "boolean": Boolean(),
    "datetime": DateTime(),
}


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
    schedule_cron: str | None = None
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


@dataclass(frozen=True)
class JobDefinition:
    site_name: str
    report_name: str
    filters: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    schedule_cron: str | None = None


@dataclass
class JobRunResult:
    site_name: str
    report_name: str
    started_at: datetime
    finished_at: datetime
    inserted_count: int = 0
    updated_count: int = 0
    pages_processed: int = 0
    rows_processed: int = 0
    status: str = "success"
    error_message: str | None = None


@dataclass(frozen=True)
class ReportCheckpoint:
    report_name: str
    checkpoint_date: str
    last_trip_number: int | None
    updated_at: datetime
