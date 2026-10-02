"""Pick the apex's language per request; leave tenants in the portal default.

The apex follows, in order: a ?lang= link, the language cookie, then the browser's Accept-Language,
falling back to English. A ?lang= choice is stored in the cookie so it carries from the home page to
the viewer. Pages are never cached by CloudFront, so per-visitor languages are safe.

Tenant pages are written in their agency's own language and are not translated, so tenants always
run in LANGUAGE_CODE. That must be activated explicitly: translation state is per thread and Django
does not reset it between requests, so a tenant request could otherwise inherit the language of the
apex request the same thread served before.

Registered through MIDDLEWARE in portal_config.yml, after django_tenants has bound the schema.
"""

from django.conf import settings
from django.db import connection
from django.middleware.locale import LocaleMiddleware
from django.utils import translation
from public_gate import PUBLIC_SCHEMA

COOKIE_MAX_AGE = 365 * 24 * 60 * 60


class ApexLocale(LocaleMiddleware):
    """LocaleMiddleware for the public schema, with ?lang= links."""

    def process_request(self, request):
        """Activate the chosen language on the apex, the default on tenants."""
        if getattr(connection, "schema_name", None) != PUBLIC_SCHEMA:
            translation.activate(settings.LANGUAGE_CODE)
            request.LANGUAGE_CODE = settings.LANGUAGE_CODE
            return
        chosen = request.GET.get("lang")
        if chosen in dict(settings.LANGUAGES):
            translation.activate(chosen)
            request.LANGUAGE_CODE = chosen
            request.chosen_language = chosen
            return
        super().process_request(request)

    def process_response(self, request, response):
        """Mark the language on apex responses and remember a ?lang= choice."""
        if getattr(connection, "schema_name", None) != PUBLIC_SCHEMA:
            return response
        response = super().process_response(request, response)
        chosen = getattr(request, "chosen_language", None)
        if chosen:
            response.set_cookie(settings.LANGUAGE_COOKIE_NAME, chosen, max_age=COOKIE_MAX_AGE, samesite="Lax", secure=request.is_secure())
        return response
