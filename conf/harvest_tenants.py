"""Register installed Tethys apps inside every tenant schema.

The Tethys harvester only ever runs against the public schema, so a tenant schema keeps an empty app
registry until this runs. The harvester swallows every exception internally, so the registry is
counted afterwards rather than trusting the call to have worked.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from tethys_apps.harvester import SingletonHarvester  # noqa: E402
from tethys_apps.models import TethysApp  # noqa: E402


def harvest():
    """Run the app harvester inside each non public tenant schema and verify the result."""
    harvester = SingletonHarvester()
    expected = len(harvester.app_modules)
    tenants = list(get_tenant_model().objects.exclude(schema_name="public"))

    if not tenants:
        print("no tenant schemas to harvest")
        return

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            harvester.harvest()
            found = TethysApp.objects.count()
            print(f"harvested {found}/{expected} apps into: {tenant.schema_name}")
            if found < expected:
                raise SystemExit(
                    f"FATAL: {tenant.schema_name} registry has {found} apps, expected {expected}"
                )


if __name__ == "__main__":
    harvest()
