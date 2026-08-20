from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import Table, and_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.engine import Engine

from automation.db.schema import build_report_table, db_metadata, job_runs_table
from automation.models import JobRunResult, ReportDefinition


class MySQLRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.metadata = db_metadata
        self.job_runs = job_runs_table

    def ensure_report_table(self, definition: ReportDefinition) -> Table:
        return build_report_table(self.metadata, definition)

    def upsert_rows(self, definition: ReportDefinition, rows: list[dict[str, Any]]) -> tuple[int, int]:
        if not rows:
            return (0, 0)

        table = self.ensure_report_table(definition)
        now = datetime.utcnow()
        prepared_rows = [
            {
                "id": self._build_row_id(definition, row),
                **row,
                "created_at": now,
                "updated_at": now,
            }
            for row in rows
        ]

        update_columns = {
            column.name: mysql_insert(table).inserted[column.name]
            for column in table.columns
            if column.name not in {"id", "created_at"}
        }
        statement = mysql_insert(table).values(prepared_rows)
        statement = statement.on_duplicate_key_update(**update_columns)

        existing_ids = {row[0] for row in self._fetch_existing_ids(table, [item["id"] for item in prepared_rows])}
        inserted_count = sum(1 for row in prepared_rows if row["id"] not in existing_ids)
        updated_count = len(prepared_rows) - inserted_count

        with self.engine.begin() as connection:
            connection.execute(statement)

        return inserted_count, updated_count

    def save_job_run(self, run_id: str, result: JobRunResult, filters: dict[str, Any]) -> None:
        payload = {
            "id": run_id,
            "site_name": result.site_name,
            "report_name": result.report_name,
            "status": result.status,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "pages_processed": result.pages_processed,
            "rows_processed": result.rows_processed,
            "inserted_count": result.inserted_count,
            "updated_count": result.updated_count,
            "error_message": result.error_message,
            "filters": filters,
        }
        with self.engine.begin() as connection:
            connection.execute(self.job_runs.insert().values(payload))

    def fetch_report_rows(
        self,
        definition: ReportDefinition,
        order_by: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        table = self.ensure_report_table(definition)
        order_column = table.c.get(order_by or "plate") or table.c.id
        statement = select(table).order_by(order_column.asc())
        if filters:
            clauses = [table.c[key] == value for key, value in filters.items() if key in table.c]
            if clauses:
                statement = statement.where(and_(*clauses))

        with self.engine.begin() as connection:
            rows = connection.execute(statement).mappings().all()

        return [dict(row) for row in rows]

    def _fetch_existing_ids(self, table: Table, row_ids: list[str]) -> list[tuple[Any, ...]]:
        with self.engine.begin() as connection:
            return list(connection.execute(select(table.c.id).where(table.c.id.in_(row_ids))))

    def _build_row_id(self, definition: ReportDefinition, row: dict[str, Any]) -> str:
        values = [str(row.get(key, "")) for key in definition.unique_keys]
        key = "|".join([definition.site_name, definition.report_name, *values])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
