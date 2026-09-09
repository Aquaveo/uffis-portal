"""Register installed Tethys apps inside every tenant schema.

The Tethys harvester only ever runs against the public schema, so a tenant schema keeps an empty
app registry until this runs. Invoked by conf/init.d/10-tenancy.sh after migrate_schemas.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from tethys_apps.harvester import SingletonHarvester  # noqa: E402


def harvest():
    """Run the app harvester once inside each non public tenant schema. Idempotent."""
    for tenant in get_tenant_model().objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            SingletonHarvester().harvest()
            print("harvested apps into:", tenant.schema_name)


harvest()
