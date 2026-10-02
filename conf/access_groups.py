"""Ensure every tenant has the group approval puts people in.

ENABLE_RESTRICTED_APP_ACCESS means a logged in account reaches no app without the object level
<package>:access_app permission, so approving someone has to put them in a group that carries it.
Groups live in the tenant schema, so the group has to exist once per tenant, and a tenant created
later needs one too.

Running this on every provision keeps that true without anyone remembering. It is additive: the
permission is granted for every app currently installed except the apex only ones, and an operator is free to make other
groups or add apps to this one.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from apex_apps import APEX_ONLY_APPS  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from guardian.shortcuts import assign_perm  # noqa: E402
from tethys_apps.models import TethysApp  # noqa: E402

GROUP_NAME = "Portal Access"


def ensure(schema):
    """Create the access group in one tenant and grant it every installed app."""
    with schema_context(schema):
        group, created = Group.objects.get_or_create(name=GROUP_NAME)
        apps = list(TethysApp.objects.exclude(package__in=APEX_ONLY_APPS))
        for app in apps:
            assign_perm(f"{app.package}:access_app", group, app)
        return created, [a.package for a in apps]


def apply():
    """Ensure the group exists in every schema, the public one included."""
    schemas = ["public"] + [
        t.schema_name for t in get_tenant_model().objects.exclude(schema_name="public")
    ]
    for schema in schemas:
        created, apps = ensure(schema)
        print(f"{schema}: group {'created' if created else 'present'}, grants {apps or 'no apps yet'}")


if __name__ == "__main__":
    apply()
