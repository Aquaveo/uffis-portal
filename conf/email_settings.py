"""Portal mail settings, built from the task environment.

Tethys reads portal_config.yml with a plain yaml.safe_load, so there is no way to interpolate an
environment variable into it, and it reads nothing but DJANGO_LOG_LEVEL from the environment
itself. ECS delivers the SMTP password as an environment variable, and portal_config.yml is a
tracked file that must not carry the account specific SMTP user either. This module bridges the
two: Tethys imports it through TETHYS_PORTAL_CONFIG.ADDITIONAL_SETTINGS_FILES and copies every
name in __all__ onto the settings module.

__all__ is the full set of mail settings this module owns, so anything set for them elsewhere in
portal_config.yml is replaced rather than half honoured. Mail is optional: with no EMAIL_HOST every
name is filled from Django's own defaults, which leaves an unconfigured portal exactly as it was.
With EMAIL_HOST set and anything else missing this raises and the container fails at boot. That
case must never reach a user: Django raises inside send at reset time, but PasswordResetView still
returns 302 and tells the person to check an inbox that will never receive anything, so nobody
reports it.
"""

import os

from django.conf import global_settings
from django.core.exceptions import ImproperlyConfigured

__all__ = [
    "DEFAULT_FROM_EMAIL",
    "EMAIL_BACKEND",
    "EMAIL_FROM",
    "EMAIL_HOST",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_HOST_USER",
    "EMAIL_PORT",
    "EMAIL_USE_TLS",
    "SERVER_EMAIL",
]

REQUIRED = ("EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL")
DEFAULT_PORT = 587
DEFAULT_DISPLAY_NAME = "UFFIS Portal"


def env(name):
    """Return an environment value with surrounding whitespace removed.

    Values reach the task through SSM and Terraform, and a trailing newline picked up on the way
    fails SMTP authentication with no indication of why. Nothing here legitimately ends in
    whitespace, including the SES SMTP password, which is base64.
    """
    return os.environ.get(name, "").strip()


def unconfigured():
    """Return Django's own mail defaults, read from global_settings rather than restated here.

    EMAIL_FROM is Tethys's, not Django's, so it falls through to the empty string the portal would
    have carried anyway.
    """
    return {name: getattr(global_settings, name, "") for name in __all__}


def mail_settings():
    """Return the Django mail settings for this task."""
    host = env("EMAIL_HOST")
    if not host:
        return unconfigured()

    missing = [name for name in REQUIRED if not env(name)]
    if missing:
        raise ImproperlyConfigured(
            f"EMAIL_HOST is set but {', '.join(missing)} empty. A half configured mail backend "
            "raises at send time, which Django reports to the user as success."
        )

    sender = env("DEFAULT_FROM_EMAIL")
    if sender.endswith(">"):
        raise ImproperlyConfigured(
            "DEFAULT_FROM_EMAIL must be a bare address. Tethys strips a trailing > from it and "
            "would send a malformed From header. The display name belongs in EMAIL_FROM."
        )

    return {
        "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "EMAIL_HOST": host,
        "EMAIL_PORT": int(env("EMAIL_PORT") or DEFAULT_PORT),
        "EMAIL_USE_TLS": True,
        "EMAIL_HOST_USER": env("EMAIL_HOST_USER"),
        "EMAIL_HOST_PASSWORD": env("EMAIL_HOST_PASSWORD"),
        "DEFAULT_FROM_EMAIL": sender,
        "SERVER_EMAIL": sender,
        "EMAIL_FROM": env("EMAIL_FROM") or DEFAULT_DISPLAY_NAME,
    }


_values = mail_settings()

DEFAULT_FROM_EMAIL = _values["DEFAULT_FROM_EMAIL"]
EMAIL_BACKEND = _values["EMAIL_BACKEND"]
EMAIL_FROM = _values["EMAIL_FROM"]
EMAIL_HOST = _values["EMAIL_HOST"]
EMAIL_HOST_PASSWORD = _values["EMAIL_HOST_PASSWORD"]
EMAIL_HOST_USER = _values["EMAIL_HOST_USER"]
EMAIL_PORT = _values["EMAIL_PORT"]
EMAIL_USE_TLS = _values["EMAIL_USE_TLS"]
SERVER_EMAIL = _values["SERVER_EMAIL"]
