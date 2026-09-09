#!/usr/bin/env bash
set -euo pipefail

tethys settings --set DATABASES.default.ENGINE django_tenants.postgresql_backend

WILDCARD="${PORTAL_WILDCARD_DOMAIN:-}"
[ -n "$WILDCARD" ] || exit 0

CFG="${TETHYS_HOME:-/home/tethys/portal}/portal_config.yml"
WILDCARD="$WILDCARD" python - "$CFG" <<'PY'
import os
import sys

import yaml


def apply_wildcard(path, wildcard):
    """Add the wildcard host to ALLOWED_HOSTS and the CSRF origin, dropping the invalid derived one."""
    suffix = wildcard.strip().lstrip("*")
    with open(path) as handle:
        cfg = yaml.safe_load(handle) or {}
    settings = cfg.setdefault("settings", {})

    hosts = list(settings.get("ALLOWED_HOSTS") or [])
    if suffix not in hosts:
        hosts.append(suffix)
    settings["ALLOWED_HOSTS"] = hosts

    origin = "https://*" + suffix
    csrf = [o for o in (settings.get("CSRF_TRUSTED_ORIGINS") or []) if o != "https://" + suffix]
    if origin not in csrf:
        csrf.append(origin)
    settings["CSRF_TRUSTED_ORIGINS"] = csrf

    with open(path, "w") as handle:
        yaml.safe_dump(cfg, handle, default_flow_style=False, sort_keys=False)
    return hosts, csrf


hosts, csrf = apply_wildcard(sys.argv[1], os.environ["WILDCARD"])
print("tenancy allowed_hosts:", hosts)
print("tenancy csrf_origins:", csrf)
PY
