"""URLs for the public schema: the apex app at /, then the whole portal.

django-tenants switches to this module for the public schema, for unknown hosts and for the load
balancer health check. Tenants keep tethys_portal.urls. The portal patterns follow the app so every
portal URL name still reverses, and PublicSchemaGate still 404s the interactive paths. Without the
app installed the list is just the portal, so / falls back to the public home page.
"""

from apex_apps import APEX_APP
from django.urls import include, re_path
from tethys_apps.harvester import SingletonHarvester
from tethys_portal import urls as portal_urls


def apex_patterns():
    """Return the apex app's HTTP patterns mounted at the site root."""
    urls = SingletonHarvester().get_url_patterns()["app_url_patterns"].get(APEX_APP, [])
    if not urls:
        return []
    return [re_path(r"^", include((urls, APEX_APP), namespace=APEX_APP))]


urlpatterns = apex_patterns() + portal_urls.urlpatterns

handler400 = portal_urls.handler400
handler403 = portal_urls.handler403
handler404 = portal_urls.handler404
handler500 = portal_urls.handler500
