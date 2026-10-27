"""Give a list of people an administrator account on every tenant.

Users are a tenant app, so auth_user is a per schema table and an account on one tenant does not
exist on another. approvers() in account_requests looks only at staff in the schema serving the
request, so anyone who should hear about every tenant's account requests needs an account in every
schema.

No address appears in this file. The list arrives in PORTAL_ADMINS, which the grant-admins workflow
takes from a repository variable, so the people holding administrator accounts are never recorded in
the repository or its history.

PORTAL_TENANTS narrows the grant to named schemas, which is how an agency's own administrator is
given their portal and nobody else's. Left empty it means every schema.

This is not a provision hook. It is run on demand by that workflow, which ships this file to a
one-off task, so it needs no image rebuild and no deploy. Run it again after adding a tenant.

The password is random and is never printed or stored anywhere this script can reach. It exists only
so the password reset flow will act on the account: PasswordResetForm.get_users filters on
has_usable_password, so an account created with set_unusable_password would silently receive no
reset mail and could never be signed into. Each administrator sets their own password through Forgot
password, once per tenant host. An existing account's password is never touched, so running this
again cannot lock anyone out.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.utils.crypto import get_random_string  # noqa: E402
from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402


def people():
    """Return the addresses to grant, or raise when the list was not supplied."""
    raw = os.environ.get("PORTAL_ADMINS", "")
    found = [address.strip() for address in raw.split(",") if address.strip()]
    if not found:
        raise SystemExit("FATAL: PORTAL_ADMINS is empty, there is nobody to grant")
    return found


def tenants():
    """Return the schemas to grant in, defaulting to every one.

    A named schema that does not exist is fatal rather than skipped. A typo would otherwise report a
    clean run that granted nobody, which is the failure that looks most like success.
    """
    known = ["public"] + sorted(
        t.schema_name for t in get_tenant_model().objects.exclude(schema_name="public")
    )
    asked = [name.strip() for name in os.environ.get("PORTAL_TENANTS", "").split(",") if name.strip()]
    if not asked:
        return known
    unknown = [name for name in asked if name not in known]
    if unknown:
        raise SystemExit(
            f"FATAL: no such tenant {', '.join(unknown)}; this portal has {', '.join(known)}"
        )
    return [name for name in known if name in asked]


def grant(address):
    """Create or reconcile one administrator in the current schema, reporting what happened.

    A username already held by a different address is left alone and reported. Two people can share
    a surname initial, and silently handing one of them another person's account would be worse than
    leaving the grant undone.
    """
    username = address.split("@")[0]

    user = User.objects.filter(email__iexact=address).first()
    if user is None:
        clash = User.objects.filter(username__iexact=username).first()
        if clash is not None:
            return f"{username}: SKIPPED, that username belongs to another address"
        User.objects.create_user(
            username=username,
            email=address,
            password=get_random_string(50),
            is_staff=True,
            is_superuser=True,
        )
        return f"{username}: created"

    granted = []
    if not user.is_staff:
        user.is_staff = True
        granted.append("staff")
    if not user.is_superuser:
        user.is_superuser = True
        granted.append("superuser")
    if granted:
        user.save(update_fields=["is_staff", "is_superuser"])
        return f"{user.username}: granted {' and '.join(granted)}"
    if not user.is_active:
        return f"{user.username}: present but inactive, left alone"
    return f"{user.username}: present"


def apply():
    """Ensure every administrator exists in each requested schema."""
    addresses = people()
    schemas = tenants()
    print(f"granting {len(addresses)} administrators across {len(schemas)}: {', '.join(schemas)}")
    for schema in schemas:
        with schema_context(schema):
            for address in addresses:
                print(f"{schema}: {grant(address)}")


if __name__ == "__main__":
    apply()
