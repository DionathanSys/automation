from automation.reports.site_alpha_reports import SITE_ALPHA_REPORTS
from automation.reports.site_beta_reports import SITE_BETA_REPORTS

REPORT_REGISTRY = {
    (report.site_name, report.report_name): report
    for report in [*SITE_ALPHA_REPORTS, *SITE_BETA_REPORTS]
}
