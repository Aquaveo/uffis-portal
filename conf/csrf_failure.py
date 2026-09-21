"""Tenant themed page for a CSRF verification failure.

Django answers a CSRF failure with a bare 403 and no explanation, which reads like the
account or the portal is broken. The usual way to reach one here is a sign in state that
changed in another tab: django.contrib.auth.login rotates the CSRF secret, so a form that
was rendered before the rotation carries a token the new secret no longer matches. An
administrator who approves an account and then returns to an already open sign in page
hits exactly that. This view names the cause and offers the way out.

Two other reasons reach the same page and need different advice, so the flags Django's own
view derives from the reason string are carried through to the template rather than dropped:
a browser that blocks the CSRF cookie, and one that withholds the Referer header. Neither
is helped by reloading, so the stale page copy would loop those visitors forever.

Wired through the CSRF_FAILURE_VIEW setting in conf/portal_config.yml.
"""

import logging

from django.middleware.csrf import REASON_NO_CSRF_COOKIE, REASON_NO_REFERER
from django.shortcuts import render
from django.views.csrf import csrf_failure as django_csrf_failure

TEMPLATE = "uffis/csrf_failure.html"

logger = logging.getLogger(f"tethys.{__name__}")


def view(request, reason="", template_name=TEMPLATE):
    """Render the themed page, falling back to Django's own on any rendering error.

    The reason string is not put in the template context. It interpolates request headers
    for some failures and the themed page removes Django's DEBUG gate around it, so only
    the two derived booleans cross the boundary. The fallback still receives it.

    The fallback is not defensive habit. This runs on a request that has already failed,
    so a missing template or a raising context processor would turn a handled 403 into an
    unhandled 500 and lose the explanation entirely.
    """
    context = {
        "user": getattr(request, "user", None),
        "no_cookie": reason == REASON_NO_CSRF_COOKIE,
        "no_referer": reason == REASON_NO_REFERER,
    }
    try:
        return render(request, template_name, context, status=403)
    except Exception:
        logger.exception("csrf failure page could not be rendered, using the stock 403")
        return django_csrf_failure(request, reason=reason)
