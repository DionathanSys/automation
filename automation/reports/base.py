from __future__ import annotations

from typing import Any

from automation.models import ReportDefinition


class BaseReport:
    definition: ReportDefinition

    @classmethod
    def normalize_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized_rows: list[dict[str, Any]] = []
        allowed_columns = {column.name for column in cls.definition.columns}

        for row in rows:
            normalized_rows.append({key: row.get(key) for key in allowed_columns})

        return normalized_rows
