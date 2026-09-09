"""Register the public tenant and the hostnames that must resolve without a tenant subdomain."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_domain_model, get_tenant_model  # noqa: E402


def public_hostnames():
    """Return the hostnames that should route to the public schema, primary first."""
    candidates = [
        os.environ.get("TETHYS_TENANT_PUBLIC_DOMAIN"),
        os.environ.get("STATIC_CLOUDFRONT_DOMAIN"),
    ]
    return [host for host in candidates if host]


def register():
    """Create the public tenant and its domain rows. Idempotent."""
    tenant_model = get_tenant_model()
    domain_model = get_tenant_domain_model()

    tenant, created = tenant_model.objects.get_or_create(
        schema_name="public", defaults={"name": "Public"}
    )
    print(f"public tenant: {'created' if created else 'exists'}")

    hosts = public_hostnames()
    if not hosts:
        print("WARNING: no public hostname configured, portal will 404 on every host")
        return

    for index, host in enumerate(hosts):
        _, made = domain_model.objects.get_or_create(
            domain=host, tenant=tenant, defaults={"is_primary": index == 0}
        )
        print(f"domain {host}: {'created' if made else 'exists'}")


register()
