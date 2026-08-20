from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table

from automation.models import ReportColumn, ReportDefinition, SQL_TYPE_MAP
from automation.reports import REPORT_REGISTRY


db_metadata = MetaData()


job_runs_table = Table(
    "job_runs",
    db_metadata,
    Column("id", String(36), primary_key=True),
    Column("site_name", String(100), nullable=False),
    Column("report_name", String(100), nullable=False),
    Column("status", String(30), nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime, nullable=False),
    Column("pages_processed", Integer, nullable=False),
    Column("rows_processed", Integer, nullable=False),
    Column("inserted_count", Integer, nullable=False),
    Column("updated_count", Integer, nullable=False),
    Column("error_message", String(1000)),
    Column("filters", JSON),
)


def build_report_table(metadata: MetaData, definition: ReportDefinition) -> Table:
    existing_table = metadata.tables.get(definition.table_name)
    if existing_table is not None:
        return existing_table

    column_names = {column.name for column in definition.columns}
    for unique_key in definition.unique_keys:
        if unique_key not in column_names:
            raise ValueError(f"Unique key '{unique_key}' nao encontrada em {definition.table_name}.")

    return Table(
        definition.table_name,
        metadata,
        Column("id", String(64), primary_key=True),
        *[_build_report_column(column) for column in definition.columns],
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )


def _build_report_column(column: ReportColumn) -> Column:
    column_type = SQL_TYPE_MAP.get(column.data_type)
    if column_type is None:
        raise ValueError(f"Tipo de coluna nao suportado: {column.data_type}")

    if column.data_type == "string" and column.length:
        column_type = String(column.length)

    return Column(column.name, column_type, nullable=column.nullable)


for report_definition in REPORT_REGISTRY.values():
    build_report_table(db_metadata, report_definition)
