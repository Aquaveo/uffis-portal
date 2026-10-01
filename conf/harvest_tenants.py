"""Register installed Tethys apps inside every tenant schema.

The Tethys harvester only ever runs against the schema that is active when it is called, and the
base image only ever calls it against public, so a tenant schema keeps an empty app registry until
this runs. The harvester swallows every exception internally and reports nothing, so the registry is
counted afterwards rather than trusting the call to have worked.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from apex_apps import APEX_ONLY_APPS  # noqa: E402
from django.contrib.auth.models import Permission  # noqa: E402
from django.db.models import Q  # noqa: E402
from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from tethys_apps.harvester import SingletonHarvester  # noqa: E402
from tethys_apps.models import TethysApp  # noqa: E402


def expected_app_count(harvester):
    """Return how many apps a healthy schema must end up with.

    SingletonHarvester.app_modules is a class attribute that stays empty until a harvest populates
    it, and TethysAppsConfig.ready only harvests when sys.argv has a subcommand, which it does not
    when this file is run directly. So public is harvested first to learn the number. A zero here
    means no app is installed in the image and every later comparison would pass vacuously.
    """
    harvester.harvest()
    count = len(harvester.app_modules)
    if count == 0:
        raise SystemExit("FATAL: the harvester found no installed apps, nothing to register")
    return count


def tenant_app_count(expected):
    """Return how many apps a tenant keeps once the apex only apps are dropped.

    Read on public after its harvest, so an apex app that is not installed is not subtracted.
    """
    return expected - TethysApp.objects.filter(package__in=APEX_ONLY_APPS).count()


def drop_apex_apps():
    """Remove apex only apps and their permissions from the active tenant schema.

    The harvester has no per app filter and registers every installed app, so this runs after
    every harvest. Deleting the permissions also deletes any group grant made on them.
    """
    TethysApp.objects.filter(package__in=APEX_ONLY_APPS).delete()
    codenames = Q()
    for package in APEX_ONLY_APPS:
        codenames |= Q(codename__startswith=f"{package}:")
    Permission.objects.filter(codenames).delete()


def harvest():
    """Run the app harvester inside each non public tenant schema and verify the result."""
    harvester = SingletonHarvester()
    expected = expected_app_count(harvester)
    print(f"public registry: {TethysApp.objects.count()}/{expected} apps")
    expected = tenant_app_count(expected)

    tenants = list(get_tenant_model().objects.exclude(schema_name="public"))
    if not tenants:
        print("no tenant schemas to harvest")
        return

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            harvester.harvest()
            drop_apex_apps()
            found = TethysApp.objects.count()
            print(f"harvested {found}/{expected} apps into: {tenant.schema_name}")
            if found < expected:
                raise SystemExit(
                    f"FATAL: {tenant.schema_name} registry has {found} apps, expected {expected}"
                )


if __name__ == "__main__":
    harvest()
