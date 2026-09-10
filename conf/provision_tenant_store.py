"""Give every tenant its own schema inside each app's persistent store database.

Tethys names a persistent store database after the app package and the setting only, so every tenant
resolves to the same physical database and the name cannot carry the tenant. The service row is per
tenant, but it only exposes host, port, username and password, and neither get_url nor get_engine
accepts connection options, so a search_path cannot be attached to the connection. That leaves the
connecting Postgres role as the only place isolation can live: one role per tenant, one schema per
tenant inside the store database, and a search_path default set on the role for that database.

The role default must be set with IN DATABASE. A cluster wide ALTER ROLE names a schema that does
not exist in the store database, and Postgres then falls back to public silently rather than
erroring, which reads and writes another tenant's rows with no sign of a fault. The assertion at the
end is the guard against exactly that, and it reads current_schema rather than SHOW search_path,
because SHOW reports the setting while current_schema reports what the connection will actually use.
"""

import os
import secrets
import string
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
sys.argv = ["manage", "shell"]
django.setup()

from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.db import connection  # noqa: E402
from django_tenants.utils import get_tenant_model, schema_context  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from tethys_apps.models import TethysApp  # noqa: E402
from tethys_services.models import PostgresPersistentStoreService  # noqa: E402

SERVICE_NAME = "tenant_store"
PUBLIC_STORE_SCHEMA = "portal_public"
ADMIN = {
    "host": os.environ["TETHYS_DB_HOST"],
    "port": os.environ.get("TETHYS_DB_PORT", "5432"),
    "user": os.environ["TETHYS_DB_USERNAME"],
    "password": os.environ["TETHYS_DB_PASSWORD"],
    "maintenance": os.environ.get("PGDATABASE") or os.environ.get("TETHYS_DB_NAME"),
}


def admin_engine(database):
    """Return an autocommit engine connected as the database owner."""
    url = "postgresql://{user}:{password}@{host}:{port}/{db}".format(db=database, **ADMIN)
    return create_engine(url, isolation_level="AUTOCOMMIT")


def quote(identifier):
    """Return a double quoted Postgres identifier, rejecting anything that cannot be one."""
    if not identifier.replace("_", "").isalnum():
        raise SystemExit(f"FATAL: refusing to use {identifier!r} as an identifier")
    return '"' + identifier + '"'


def new_password():
    """Return a password with no characters that need escaping in a connection URL."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


def store_schema_for(schema_name):
    """Return the schema this tenant owns inside a store database.

    The public tenant cannot use a store schema called public. That schema already exists in every
    database, is the fallback Postgres uses when a search_path entry is missing, and is the one the
    other roles are revoked from, so pointing the public tenant at it would make a misprovisioned
    tenant land in real data instead of an empty schema.
    """
    return PUBLIC_STORE_SCHEMA if schema_name == "public" else schema_name


def store_databases(schema_name):
    """Return the store database names this tenant's installed apps resolve to."""
    with schema_context(schema_name):
        names = set()
        for app in TethysApp.objects.all():
            for setting in app.persistent_store_database_settings:
                names.add(setting.get_namespaced_persistent_store_name())
    return sorted(names)


def ensure_role(conn, role, password):
    """Create the tenant's login role, or reset its password when it already exists.

    The admin is granted membership of the new role because creating a schema owned by another role
    requires being able to SET ROLE to it. A local Postgres hides this: the container's POSTGRES_USER
    is a superuser and bypasses the check, while a managed instance gives you a privileged but non
    superuser master that fails with "must be able to SET ROLE".
    """
    exists = conn.execute(f"select 1 from pg_roles where rolname = '{role}'").first()
    verb = "alter" if exists else "create"
    conn.execute(f"{verb} role {quote(role)} with login password '{password}'")
    conn.execute(f"grant {quote(role)} to {quote(ADMIN['user'])}")
    return verb


def ensure_database(conn, database, role):
    """Create the store database if absent, owned by the admin role, and let the tenant connect."""
    exists = conn.execute(f"select 1 from pg_database where datname = '{database}'").first()
    if not exists:
        conn.execute(f"create database {quote(database)}")
    conn.execute(f"grant connect on database {quote(database)} to {quote(role)}")
    return bool(exists)


def ensure_schema(database, schema_name, role):
    """Create the tenant's schema inside the store database and pin the role's search_path to it."""
    with admin_engine(database).connect() as conn:
        conn.execute(f"create schema if not exists {quote(schema_name)} authorization {quote(role)}")
        conn.execute(f"revoke create on schema public from {quote(role)}")
        conn.execute("revoke all on schema public from public")
        conn.execute(
            f"alter role {quote(role)} in database {quote(database)} "
            f"set search_path = {quote(schema_name)}"
        )


def assert_isolated(database, schema_name, role, password):
    """Connect as the tenant role and fail unless Postgres actually resolves to its schema."""
    url = "postgresql://{u}:{p}@{host}:{port}/{db}".format(
        u=role, p=password, host=ADMIN["host"], port=ADMIN["port"], db=database
    )
    with create_engine(url).connect() as conn:
        actual = conn.execute("select current_schema()").first()[0]
    if actual != schema_name:
        raise SystemExit(
            f"FATAL: {role} resolves to schema {actual!r} in {database}, expected {schema_name!r}. "
            "Writes would land in another tenant's schema."
        )
    print(f"    isolation asserted: current_schema() is {actual}")


def link_service(schema_name, role, password):
    """Point every store setting in this tenant schema at a service using the tenant's role."""
    with schema_context(schema_name):
        service, created = PostgresPersistentStoreService.objects.get_or_create(
            name=SERVICE_NAME,
            defaults={"host": ADMIN["host"], "port": int(ADMIN["port"]), "username": role},
        )
        service.host = ADMIN["host"]
        service.port = int(ADMIN["port"])
        service.username = role
        service.password = password
        service.save()
        print(f"    service {SERVICE_NAME}: {'created' if created else 'updated'}")

        content_type = ContentType.objects.get_for_model(PostgresPersistentStoreService)
        for app in TethysApp.objects.all():
            for setting in app.persistent_store_database_settings:
                already = setting.content_type_id == content_type.id and setting.object_id == service.id
                if not already:
                    setting.persistent_store_service = service
                    setting.save()
                    print(f"    linked {app.package}.{setting.name}")


def existing_password(schema_name):
    """Return the password already stored on this tenant's service row, if there is one."""
    with schema_context(schema_name):
        service = PostgresPersistentStoreService.objects.filter(name=SERVICE_NAME).first()
        return service.password if service else None


def provision():
    """Provision an isolated store schema for every tenant, the public one included."""
    tenants = list(get_tenant_model().objects.all())
    if not tenants:
        print("no tenants to provision")
        return

    for tenant in tenants:
        schema_name = tenant.schema_name
        store_schema = store_schema_for(schema_name)
        role = f"{schema_name}_store"
        print(f"tenant {schema_name} (store schema {store_schema}):")

        databases = store_databases(schema_name)
        if not databases:
            print("    no app declares a persistent store, nothing to do")
            continue

        password = existing_password(schema_name) or new_password()
        with admin_engine(ADMIN["maintenance"]).connect() as conn:
            verb = ensure_role(conn, role, password)
            print(f"    role {role}: {verb}d")
            for database in databases:
                had = ensure_database(conn, database, role)
                print(f"    database {database}: {'exists' if had else 'created'}")

        for database in databases:
            ensure_schema(database, store_schema, role)
            assert_isolated(database, store_schema, role, password)

        link_service(schema_name, role, password)


if __name__ == "__main__":
    provision()
    connection.close()
