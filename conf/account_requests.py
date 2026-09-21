"""Self service account requests: the address is confirmed, then a person approves.

Tethys's own sign up creates an active account and logs the person straight in. On a portal serving
national meteorological services that is too much: anyone reaching the page would hold an account on
that agency's portal.

This replaces it with two gates. Registration creates the account inactive and emails a signed link;
following that link proves the address belongs to whoever used it. Only then are the tenant's own
administrators told there is someone to review, so a robot that never reads the mailbox never
reaches a human. Approval is the second gate and is done by a person.

Nothing here stores a token. Both links carry a signed payload naming the user and the schema it was
issued under, so a link minted on one tenant cannot be replayed against another, and an expired one
simply stops verifying.

Tethys imports the controller through TETHYS_PORTAL_CONFIG.REGISTER_CONTROLLER and the two endpoints
through ADDITIONAL_URLPATTERNS, so no part of the portal is patched.
"""

import logging

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.models import Group, User
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, dumps, loads
from django.db import connection
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.views.decorators.cache import never_cache
from tethys_config.models import get_custom_template
from tethys_portal.forms import RegisterForm

log = logging.getLogger(__name__)

CONFIRM_SALT = "uffis.account.confirm"
APPROVE_SALT = "uffis.account.approve"
CONFIRM_MAX_AGE = 3 * 24 * 60 * 60
APPROVE_MAX_AGE = 30 * 24 * 60 * 60
APP_ACCESS_GROUP = "Portal Access"


def schema():
    """Return the schema this request is bound to, which names the tenant."""
    return getattr(connection, "schema_name", "") or ""


def mint(salt, user):
    """Return a signed token naming a user and the tenant it belongs to."""
    return dumps({"uid": user.pk, "schema": schema()}, salt=salt)


def redeem(salt, token, max_age):
    """Return the user a token names, or None if it is expired, forged or from another tenant."""
    try:
        payload = loads(token, salt=salt, max_age=max_age)
    except SignatureExpired:
        log.info("account token expired on %s", schema())
        return None
    except BadSignature:
        log.warning("account token failed to verify on %s", schema())
        return None
    if payload.get("schema") != schema():
        log.warning("account token for %s replayed on %s", payload.get("schema"), schema())
        return None
    return User.objects.filter(pk=payload.get("uid")).first()


def absolute(request, location):
    """Return a full URL for this tenant's host, honouring whether the request arrived over TLS."""
    return f"{'https' if request.is_secure() else 'http'}://{request.get_host()}{location}"


def site_name(request):
    """Return the portal's own name for this tenant, falling back to its hostname."""
    return getattr(request, "site_globals", {}).get("brand_text") or request.get_host()


def approvers():
    """Return the addresses of every administrator on this tenant who can be written to."""
    return list(
        User.objects.filter(is_staff=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def post(subject, template, context, recipients):
    """Send one message, logging rather than raising when the portal has no mail configured."""
    if not recipients:
        log.error("no recipients for %r on %s, the message was dropped", subject, schema())
        return False
    try:
        send_mail(
            subject=subject,
            message=render_to_string(template, context),
            from_email=None,
            recipient_list=recipients,
            fail_silently=False,
        )
        return True
    except Exception:
        log.exception("could not send %r on %s", subject, schema())
        return False


@never_cache
def register(request):
    """Take a request for an account, create it inactive and email the address to confirm it."""
    if not request.user.is_anonymous:
        return redirect("user:profile")
    if not getattr(settings, "ENABLE_OPEN_SIGNUP", False):
        return redirect("accounts:login")

    if request.method == "POST" and "register-submit" in request.POST:
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            link = absolute(request, reverse("account_confirm", args=[mint(CONFIRM_SALT, user)]))
            post(
                f"Confirm your {site_name(request)} account",
                "registration/confirm_email.txt",
                {"user": user, "link": link, "site": site_name(request), "days": CONFIRM_MAX_AGE // 86400},
                [user.email],
            )
            return render(request, "registration/request_received.html", {"email": user.email})
    else:
        form = RegisterForm()

    template = get_custom_template("Register Page Template", "tethys_portal/accounts/register.html")
    return render(request, template, {"form": form})


@never_cache
def confirm(request, token):
    """Mark the address proven and tell this tenant's administrators there is someone to review."""
    user = redeem(CONFIRM_SALT, token, CONFIRM_MAX_AGE)
    if user is None:
        return render(request, "registration/confirm_invalid.html", status=400)

    if user.is_active:
        return render(request, "registration/confirm_done.html", {"already": True})

    link = absolute(request, reverse("account_approve", args=[mint(APPROVE_SALT, user)]))
    post(
        f"Account request on {site_name(request)}: {user.username}",
        "registration/approval_email.txt",
        {"requester": user, "link": link, "site": site_name(request), "host": request.get_host()},
        approvers(),
    )
    return render(request, "registration/confirm_done.html", {"already": False})


@never_cache
def approve(request, token):
    """Activate an account and grant it the portal, for a signed link opened by a staff session.

    The token alone is not authority. Email is not an authenticated channel, and a forwarded message
    should not be able to admit anyone, so this refuses without a staff session and sends the visitor
    to log in first.
    """
    if not (request.user.is_authenticated and request.user.is_staff):
        return redirect(f"{reverse('accounts:login')}?next={request.path}")

    user = redeem(APPROVE_SALT, token, APPROVE_MAX_AGE)
    if user is None:
        messages.error(request, "That approval link is no longer valid. Use the list below instead.")
        return redirect("admin:auth_user_changelist")

    admitted = admit(user, request)
    messages.success(
        request,
        f"{user.username} is approved and was emailed."
        if admitted
        else f"{user.username} is approved. The notification could not be sent, see the logs.",
    )
    return redirect("admin:auth_user_change", user.pk)


def admit(user, request):
    """Activate a user, put them in the access group and tell them. Returns whether mail was sent."""
    user.is_active = True
    user.save(update_fields=["is_active"])

    group = Group.objects.filter(name=APP_ACCESS_GROUP).first()
    if group is None:
        log.error(
            "group %r is missing on %s, %s is active but reaches no app",
            APP_ACCESS_GROUP, schema(), user.username,
        )
    else:
        user.groups.add(group)

    return post(
        f"Your {site_name(request)} account is ready",
        "registration/approved_email.txt",
        {"user": user, "site": site_name(request), "link": absolute(request, reverse("accounts:login"))},
        [user.email],
    )


@admin.action(description="Approve: activate, grant the portal and notify")
def approve_selected(modeladmin, request, queryset):
    """Approve every selected request at once, so a backlog is one action rather than many."""
    done = 0
    for user in queryset.filter(is_active=False):
        admit(user, request)
        done += 1
    if done:
        messages.success(request, f"Approved {done} account(s) and emailed them.")
    else:
        messages.info(request, "Nothing to approve, every account selected was already active.")


def register_admin_action():
    """Add the bulk approval to the user list Tethys already registers.

    Re-registering is the supported way to extend another package's ModelAdmin. The guard keeps a
    second import from stacking the action twice.
    """
    current = admin.site._registry.get(User)
    if current is None or approve_selected in (current.actions or []):
        return
    base = type(current)
    admin.site.unregister(User)
    admin.site.register(
        User,
        type("ApprovingUserAdmin", (base,), {"actions": [*(base.actions or []), approve_selected]}),
    )


register_admin_action()

urlpatterns = [
    path("accounts/confirm/<str:token>/", confirm, name="account_confirm"),
    path("accounts/approve/<str:token>/", approve, name="account_approve"),
]
