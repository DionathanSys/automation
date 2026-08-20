from automation.sites.site_alpha import SiteAlpha
from automation.sites.site_beta import SiteBeta
from automation.sites.site_sascar import SiteSascar

SITE_REGISTRY = {
    SiteAlpha.site_name: SiteAlpha,
    SiteBeta.site_name: SiteBeta,
    SiteSascar.site_name: SiteSascar,
}
