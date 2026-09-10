"""Register the public tenant and the hostnames that must resolve without a tenant subdomain."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django_tenants.utils import get_tenant_domain_model, get_tenant_model  # noqa: E402

PORTAL_DOMAIN = "uffis.org"


def public_hostnames():
    """Return the hostnames routing to the public schema, primary first.

    The CloudFront distribution domain is only known at deploy time, so it comes from the task
    environment. The portal domain is portal owned and never arrives that way.
    """
    hosts = [PORTAL_DOMAIN]
    cdn = os.environ.get("STATIC_CLOUDFRONT_DOMAIN")
    if cdn and cdn not in hosts:
        hosts.append(cdn)
    return hosts


def claim(domain_model, tenant, host, primary):
    """Create or reconcile one Domain row, leaving rows owned by another tenant alone."""
    existing = domain_model.objects.filter(domain=host).first()
    if existing is not None:
        if existing.tenant_id != tenant.pk:
            print(f"domain {host}: owned by tenant {existing.tenant.schema_name}, leaving it alone")
            return
        if primary and not existing.is_primary:
            existing.is_primary = True
            existing.save()
            print(f"domain {host}: promoted to primary")
        else:
            print(f"domain {host}: exists")
        return
    domain_model.objects.create(domain=host, tenant=tenant, is_primary=primary)
    print(f"domain {host}: created")


def register():
    """Create the public tenant and its domain rows. Idempotent."""
    tenant_model = get_tenant_model()
    domain_model = get_tenant_domain_model()

    tenant, created = tenant_model.objects.get_or_create(
        schema_name="public", defaults={"name": "Public"}
    )
    print(f"public tenant: {'created' if created else 'exists'}")

    for host in public_hostnames():
        claim(domain_model, tenant, host, host == PORTAL_DOMAIN)

    if not domain_model.objects.filter(tenant=tenant, domain=PORTAL_DOMAIN).exists():
        raise SystemExit(f"FATAL: {PORTAL_DOMAIN} has no Domain row, the portal would 404")


if __name__ == "__main__":
    register()
