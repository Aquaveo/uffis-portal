"""Portal S3 storage backends.

Static is deliberately shared. Every object under it is a framework or app asset collected from an
installed package, byte identical for every tenant and public read through CloudFront, so isolating
it would duplicate it per tenant and fragment the cache without creating a boundary.

Media is per tenant. Uploads are written by tenant users, and the store side already isolates rows
by schema, so leaving the bucket shared would put the weaker boundary on the more sensitive data.
"""

from django.db import connection
from storages.backends.s3 import S3Storage

PUBLIC_MEDIA_PREFIX = "portal_public"

# Unhashed static names need short caching
STATIC_CACHE_CONTROL = "public, max-age=300"


def tenant_prefix():
    """Return the media prefix for the schema this connection is bound to.

    Outside a request django_tenants leaves the connection on the public schema rather than on no
    schema, so a management command or background job writes under the public tenant's prefix.
    Measured, not assumed: connection.schema_name reads "public" there. That is the safe outcome,
    since it can never reach another tenant's files, but it does mean a job that meant to write for
    a tenant must enter schema_context itself; nothing here can detect that it forgot.

    Public gets its own prefix rather than the bucket root so that every object is owned by exactly
    one tenant, which keeps an unprefixed legacy key from resolving into anyone's namespace.
    """
    schema = getattr(connection, "schema_name", None)
    if not schema:
        raise RuntimeError("media storage was used with no schema bound to the connection")
    return PUBLIC_MEDIA_PREFIX if schema == "public" else schema


class PortalStaticS3Storage(S3Storage):
    """Shared static assets, with leading slashes stripped so keys resolve under the location.

    Static keys are not content hashed, so a deploy changes a file in place. With no Cache-Control,
    CloudFront's CachingOptimized policy keeps an object for a day, and it caches each encoding
    separately: after one deploy browsers got the old brotli main.js beside the new page and the
    viewer crashed while plain requests looked fine. Five minutes bounds how stale a deploy can be.
    """

    def get_object_parameters(self, name):
        """Add the static Cache-Control to every uploaded object unless one is configured."""
        params = super().get_object_parameters(name)
        params.setdefault("CacheControl", STATIC_CACHE_CONTROL)
        return params

    def url(self, name, *args, **kwargs):
        if isinstance(name, str):
            name = name.lstrip("/")
        return super().url(name, *args, **kwargs)


class TenantMediaS3Storage(S3Storage):
    """Media keyed under the current tenant.

    _normalize_name is the single seam every path resolving operation goes through on
    django-storages 1.14.6: _open, _save, delete, exists, listdir, size and url all call it, so
    prefixing here covers reads, writes and URL generation without overriding each one.
    """

    def _normalize_name(self, name):
        return super()._normalize_name(f"{tenant_prefix()}/{name.lstrip('/')}")
