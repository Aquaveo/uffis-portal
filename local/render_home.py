"""Render the public home template to stdout, for before and after diffs."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tethys_portal.settings")
django.setup()

from django.contrib.auth.models import AnonymousUser  # noqa: E402
from django.template.loader import render_to_string  # noqa: E402
from django.test import RequestFactory  # noqa: E402
from django_tenants.utils import schema_context  # noqa: E402


def render():
    """Return the public home rendered as an anonymous visitor."""
    with schema_context("public"):
        request = RequestFactory().get("/", HTTP_HOST="localhost")
        request.user = AnonymousUser()
        return render_to_string("tenants/public/home.html", request=request)


if __name__ == "__main__":
    print(render())
