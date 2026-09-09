"""Add the tenant wildcard host and its CSRF origin to the rendered portal config.

CloudFront, Django ALLOWED_HOSTS and Django CSRF_TRUSTED_ORIGINS each want a different spelling of
the same wildcard. This writes the two Django forms; the CloudFront form lives in tofu/uffis.tfvars.
"""

import os
import sys

import yaml

from portal_identity import PORTAL_DOMAIN


def normalize(domain):
    """Return the Django subdomain wildcard form, a leading dot, for a portal domain."""
    raw = domain.strip().lstrip("*").strip()
    if not raw.strip("."):
        raise SystemExit(f"not a domain: {domain!r}")
    return raw if raw.startswith(".") else "." + raw


def apply_wildcard(path, domain):
    """Append the wildcard host to ALLOWED_HOSTS and its origin to CSRF_TRUSTED_ORIGINS."""
    suffix = normalize(domain)
    with open(path) as handle:
        cfg = yaml.safe_load(handle) or {}
    settings = cfg.setdefault("settings", {})

    hosts = list(settings.get("ALLOWED_HOSTS") or [])
    if suffix not in hosts:
        hosts.append(suffix)
    settings["ALLOWED_HOSTS"] = hosts

    origin = "https://*" + suffix
    csrf = list(settings.get("CSRF_TRUSTED_ORIGINS") or [])
    if origin not in csrf:
        csrf.append(origin)
    settings["CSRF_TRUSTED_ORIGINS"] = csrf

    with open(path, "w") as handle:
        yaml.safe_dump(cfg, handle, default_flow_style=False, sort_keys=False)
    return hosts, csrf


if __name__ == "__main__":
    config = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TETHYS_HOME", "/home/tethys/portal"), "portal_config.yml"
    )
    allowed, origins = apply_wildcard(config, PORTAL_DOMAIN)
    print("tenancy allowed_hosts:", allowed)
    print("tenancy csrf_origins:", origins)
