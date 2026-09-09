#!/usr/bin/env bash
set -euo pipefail

[ -n "${ECS_CONTAINER_METADATA_URI_V4:-}" ] || exit 0

CFG="${TETHYS_HOME:-/home/tethys/portal}/portal_config.yml"
TASK_IP="$(curl -s --max-time 3 "${ECS_CONTAINER_METADATA_URI_V4}/task" \
  | python -c 'import sys,json
try:
    d=json.load(sys.stdin)
    ips=[a for c in d.get("Containers",[]) for n in c.get("Networks",[]) for a in n.get("IPv4Addresses",[])]
    print(ips[0] if ips else "")
except Exception:
    print("")' 2>/dev/null || true)"
[ -n "$TASK_IP" ] || { echo "no task IP found, skipping"; exit 0; }

TASK_IP="$TASK_IP" python - "$CFG" <<'PY'
import os
import sys

import yaml


def add_task_ip(path, ip):
    """Append the running task private IP to ALLOWED_HOSTS so the ALB health check passes."""
    with open(path) as handle:
        cfg = yaml.safe_load(handle) or {}
    settings = cfg.setdefault("settings", {})
    hosts = list(settings.get("ALLOWED_HOSTS") or [])
    if ip and ip not in hosts:
        hosts.append(ip)
        settings["ALLOWED_HOSTS"] = hosts
        with open(path, "w") as handle:
            yaml.safe_dump(cfg, handle, default_flow_style=False, sort_keys=False)
    return ip


print("added task IP to ALLOWED_HOSTS:", add_task_ip(sys.argv[1], os.environ["TASK_IP"].strip()))
PY
