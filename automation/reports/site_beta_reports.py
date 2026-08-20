from automation.models import ReportColumn, ReportDefinition


SITE_BETA_REPORTS = [
    ReportDefinition(
        site_name="site_beta",
        report_name="sales_by_day",
        table_name="site_beta_sales_by_day",
        unique_keys=["external_id"],
        columns=[
            ReportColumn(name="external_id", data_type="string", nullable=False),
            ReportColumn(name="sale_date", data_type="string"),
            ReportColumn(name="store_name", data_type="string"),
            ReportColumn(name="gross_amount", data_type="float"),
            ReportColumn(name="net_amount", data_type="float"),
        ],
        description="Vendas por dia placeholder do site beta.",
    ),
    ReportDefinition(
        site_name="site_beta",
        report_name="inventory_position",
        table_name="site_beta_inventory_position",
        unique_keys=["external_id"],
        columns=[
            ReportColumn(name="external_id", data_type="string", nullable=False),
            ReportColumn(name="sku", data_type="string"),
            ReportColumn(name="product_name", data_type="string"),
            ReportColumn(name="stock_quantity", data_type="integer"),
            ReportColumn(name="updated_at_source", data_type="string"),
        ],
        description="Posicao de estoque placeholder do site beta.",
    ),
]
