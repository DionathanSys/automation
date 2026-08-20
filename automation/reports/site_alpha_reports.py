from automation.models import ReportColumn, ReportDefinition


SITE_ALPHA_REPORTS = [
    ReportDefinition(
        site_name="site_alpha",
        report_name="financial_summary",
        table_name="site_alpha_financial_summary",
        unique_keys=["external_id"],
        columns=[
            ReportColumn(name="external_id", data_type="string", nullable=False),
            ReportColumn(name="reference_date", data_type="string"),
            ReportColumn(name="description", data_type="string"),
            ReportColumn(name="amount", data_type="float"),
            ReportColumn(name="status", data_type="string"),
        ],
        description="Resumo financeiro placeholder do site alpha.",
    ),
    ReportDefinition(
        site_name="site_alpha",
        report_name="open_titles",
        table_name="site_alpha_open_titles",
        unique_keys=["external_id"],
        columns=[
            ReportColumn(name="external_id", data_type="string", nullable=False),
            ReportColumn(name="customer_name", data_type="string"),
            ReportColumn(name="due_date", data_type="string"),
            ReportColumn(name="amount", data_type="float"),
            ReportColumn(name="status", data_type="string"),
        ],
        description="Titulos em aberto placeholder do site alpha.",
    ),
    ReportDefinition(
        site_name="site_alpha",
        report_name="monitoring_trips",
        table_name="site_alpha_monitoring_trips",
        unique_keys=["external_id"],
        columns=[
            ReportColumn(name="external_id", data_type="string", nullable=False),
            ReportColumn(name="plate", data_type="string", nullable=False),
            ReportColumn(name="started_at", data_type="datetime"),
            ReportColumn(name="current_location", data_type="string", length=1000),
            ReportColumn(name="status", data_type="string", length=255),
            ReportColumn(name="weight", data_type="float"),
            ReportColumn(name="destination", data_type="string", length=1000),
            ReportColumn(name="collected_at", data_type="datetime", nullable=False),
        ],
        description="Viagens em andamento do monitoramento do site alpha.",
    ),
    ReportDefinition(
        site_name="site_alpha",
        report_name="daily_trip_summary",
        table_name="site_alpha_daily_trip_summary",
        unique_keys=["external_id"],
        columns=[
            ReportColumn(name="external_id", data_type="string", nullable=False),
            ReportColumn(name="report_date", data_type="string", nullable=False),
            ReportColumn(name="plate", data_type="string", nullable=False),
            ReportColumn(name="fleet", data_type="string"),
            ReportColumn(name="vehicle_id", data_type="integer"),
            ReportColumn(name="completed_trip_count", data_type="integer", nullable=False),
            ReportColumn(name="total_suggested_km", data_type="float", nullable=False),
            ReportColumn(name="total_driven_km", data_type="float", nullable=False),
            ReportColumn(name="collected_at", data_type="datetime", nullable=False),
        ],
        description="Resumo diario de viagens encerradas por veiculo do site alpha.",
    ),
]
