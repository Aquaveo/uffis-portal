"""Create one local tenant, so tenant isolation can be checked on this machine.

Production tenants are created by an operator. Locally the database starts empty, so this makes
the ABMS tenant at abms.localhost. Idempotent: an existing tenant or domain is left alone.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import (  # noqa: E402
    get_tenant_domain_model,
    get_tenant_model,
    schema_context,
)
from tethys_config.models import Setting  # noqa: E402

SCHEMA = "abms"
NAME = "Antigua and Barbuda Meteorological Services"
DOMAIN = "abms.localhost"
HOME_TEMPLATE = f"tenants/{SCHEMA}/home.html"


def seed():
    """Create the tenant and its domain row when they are missing."""
    tenant, created = get_tenant_model().objects.get_or_create(schema_name=SCHEMA, defaults={"name": NAME})
    print(f"tenant {SCHEMA}: {'created' if created else 'exists'}")
    _, created = get_tenant_domain_model().objects.get_or_create(
        domain=DOMAIN, defaults={"tenant": tenant, "is_primary": True}
    )
    print(f"domain {DOMAIN}: {'created' if created else 'exists'}")



def pin_home_template():
    """Give the tenant its agency home, as an operator does in production admin."""
    with schema_context(SCHEMA):
        Setting.objects.filter(name="Home Page Template").update(content=HOME_TEMPLATE)
    print(f"tenant {SCHEMA}: home template {HOME_TEMPLATE}")


if __name__ == "__main__":
    seed()
    pin_home_template()
