"""Apply the portal site settings inside every tenant schema.

tethys_config is a tenant app, so each tenant schema owns its own settings tables. The base image
runs `tethys site -f` once, before the provisioning hooks and on the public schema, so tenants would
otherwise render stock Tethys branding.
"""

import os

import django
import yaml

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from tethys_cli.site_commands import update_site_settings_content  # noqa: E402


def site_settings():
    """Return the site_settings block from the rendered portal config, or an empty dict."""
    path = os.path.join(os.environ.get("TETHYS_HOME", "/home/tethys/portal"), "portal_config.yml")
    with open(path) as handle:
        cfg = yaml.safe_load(handle) or {}
    return cfg.get("site_settings") or {}


def apply():
    """Write the portal site settings into each non public tenant schema."""
    settings = site_settings()
    if not settings:
        print("no site_settings configured")
        return

    for tenant in get_tenant_model().objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            for values in settings.values():
                update_site_settings_content(values)
            print("applied site settings to:", tenant.schema_name)


if __name__ == "__main__":
    apply()
