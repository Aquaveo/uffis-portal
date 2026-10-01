"""Keep the public schema to its landing page.

Real work happens on the tenant subdomains. The public schema still served a complete portal, so
anyone could sign up on it, and because SHOW_PUBLIC_IF_NO_TENANT_FOUND is on it answered for the
CloudFront domain and for every unrecognised Host as well. Removing the apex DNS record would have
closed one of those three doors. This closes all of them, because it gates on the schema rather
than on the hostname.

Blocking rather than allowing. The load balancer health checks GET / against the load balancer's own
name, which is not a tenant, so that request lands here on the public schema and has to keep
returning 200 or the service is replaced. An allowlist that forgot it would take the portal down,
so the landing page stays reachable by default and only the interactive surfaces are named.

Registered through MIDDLEWARE in portal_config.yml, which Tethys appends after its own list, so this
runs after django_tenants has bound the schema and there is a schema to read.
"""

from apex_apps import APEX_APP_PATHS
from django.conf import settings
from django.db import connection
from django.http import Http404

PUBLIC_SCHEMA = "public"

BLOCKED_PREFIXES = (
    "/accounts/",
    "/user/",
    "/apps/",
    "/admin/",
    "/oauth2/",
    "/handoff/",
)


def _unprefixed(path):
    """Return the path with the portal's PREFIX_URL removed, so the prefix cannot be used to slip past."""
    prefix = (getattr(settings, "PREFIX_URL", "") or "").strip("/")
    if prefix and path.startswith(f"/{prefix}/"):
        return path[len(prefix) + 1 :]
    return path


class PublicSchemaGate:
    """Answer 404 for the portal's interactive paths while the request is on the public schema."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        schema = getattr(connection, "schema_name", None)
        if schema == PUBLIC_SCHEMA and _unprefixed(request.path).startswith(BLOCKED_PREFIXES):
            raise Http404("not available on this host")
        return self.get_response(request)


class TenantAppGate:
    """Answer 404 for apex only apps while the request is on a tenant schema.

    Every installed app has URLs on every schema, because the URLconf is shared. Dropping the app's
    row from a tenant registry hides it from the library but leaves the route, and the apex view
    takes anonymous visitors, so the path itself is closed here.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        schema = getattr(connection, "schema_name", None)
        if schema not in (None, PUBLIC_SCHEMA) and _unprefixed(request.path).startswith(APEX_APP_PATHS):
            raise Http404("not available on this host")
        return self.get_response(request)
