#!/usr/bin/env bash
set -euo pipefail

# Provision, seed, rerun hooks
/usr/local/bin/provision.sh
python /opt/portal-local/seed_tenant.py
for hook in /opt/portal/init.d/*.sh; do
  echo "Rerunning provision hook: $(basename "$hook")"
  bash "$hook"
done
