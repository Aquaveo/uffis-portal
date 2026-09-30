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
from datetime import UTC, datetime

import django
import yaml

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from tethys_cli.site_commands import update_site_settings_content  # noqa: E402
from tethys_config.models import Setting  # noqa: E402

STOCK_SITE_TITLE = "Tethys Portal"
PUBLIC_HOME_TEMPLATE = "tenants/public/home.html"
# The apex carries no agency branding of its own, so it keeps the stock Tethys values unless
# they are set here: site_tenants seeds tenants only, and portal_config.yml names neither.
# Brand Text is rendered twice, in the header bar and in the identity chip above the headline, so
# one value settles both. The year is computed rather than written down, so the copyright does not
# go stale in January. The tenants each name their own agency; the apex speaks for the programme.
PUBLIC_SETTINGS = {
    "Brand Text": "UFFIS Portal",
    "Primary Text Hover Color": "#faaf00",
    "Footer Copyright": f"Copyright \u00a9 {datetime.now(UTC):%Y} UFFIS",
}


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


def pin_public_home():
    """Point the public schema at the apex landing page.

    Pinned on every provision rather than seeded once, unlike the tenant settings above. The public
    admin is closed, so there is no operator edit here to protect, and if this were lost the apex
    would fall back to the stock portal home carrying the login and sign up links that closing it
    was meant to remove.
    """
    with schema_context("public"):
        setting = Setting.objects.filter(name="Home Page Template").first()
        if setting is None:
            print("public: no Home Page Template setting to pin")
            return
        if setting.content == PUBLIC_HOME_TEMPLATE:
            print("public: home template already pinned")
            return
        setting.content = PUBLIC_HOME_TEMPLATE
        setting.save()
        print("public: home template pinned to", PUBLIC_HOME_TEMPLATE)


def pin_public_branding():
    """Give the apex the portal's own name and accent instead of the stock Tethys ones."""
    with schema_context("public"):
        for name, content in PUBLIC_SETTINGS.items():
            setting = Setting.objects.filter(name=name).first()
            if setting is None:
                print(f"public: no {name} setting to pin")
                continue
            if setting.content == content:
                continue
            setting.content = content
            setting.save()
            print(f"public: {name} pinned to {content}")


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
    pin_public_home()
    pin_public_branding()
