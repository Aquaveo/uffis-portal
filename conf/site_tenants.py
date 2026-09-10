"""Seed the portal site settings into a tenant schema once.

tethys_config is a tenant app, so each tenant schema owns its own settings tables. The base image
runs `tethys site -f` once, before the provisioning hooks and on the public schema, so a new tenant
would otherwise render stock Tethys branding.

Seeding runs once per tenant, not on every provision. Applying the portal defaults unconditionally
overwrites whatever an operator has since set for that tenant, which is the opposite of what per
tenant branding is for. It happened: a deploy silently reverted a tenant's colours to the portal
palette while leaving the settings absent from portal_config.yml alone, so the tenant rendered half
its own theme and half the default one.

A tenant counts as untouched while its Site Title still holds the stock Tethys value. That is the
first thing seeding changes, so the marker flips on the first run and never flips back.
"""

import os

import django
import yaml

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from tethys_cli.site_commands import update_site_settings_content  # noqa: E402
from tethys_config.models import Setting  # noqa: E402

STOCK_SITE_TITLE = "Tethys Portal"


def site_settings():
    """Return the site_settings block from the rendered portal config, or an empty dict."""
    path = os.path.join(os.environ.get("TETHYS_HOME", "/home/tethys/portal"), "portal_config.yml")
    with open(path) as handle:
        cfg = yaml.safe_load(handle) or {}
    return cfg.get("site_settings") or {}


def is_untouched():
    """Return whether this tenant still carries the stock site title."""
    setting = Setting.objects.filter(name="Site Title").first()
    return setting is not None and setting.content == STOCK_SITE_TITLE


def apply():
    """Seed the portal site settings into each tenant schema that has not been customised."""
    settings = site_settings()
    if not settings:
        print("no site_settings configured")
        return

    for tenant in get_tenant_model().objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            if not is_untouched():
                print("site settings already customised, leaving alone:", tenant.schema_name)
                continue
            for values in settings.values():
                update_site_settings_content(values)
            print("seeded site settings into:", tenant.schema_name)


if __name__ == "__main__":
    apply()
