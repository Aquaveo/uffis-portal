"""Answer a short notice on every page of a paused tenant.

A paused tenant keeps its schema, accounts and settings; only its pages stop answering, login and
admin included. Resume by removing its schema from PAUSED_TENANTS and redeploying.

Registered through MIDDLEWARE in portal_config.yml, which Tethys appends after its own list, so this
runs after django_tenants has bound the schema. The public schema is never listed, so the load
balancer health check is unaffected.
"""

from django.db import connection
from django.shortcuts import render

# Barbados asked for a pause
PAUSED_TENANTS = ("bms",)


class PausedTenantGate:
    """Answer 503 with a notice for every path on a paused tenant."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(connection, "schema_name", None) in PAUSED_TENANTS:
            return render(request, "uffis/paused.html", status=503)
        return self.get_response(request)
