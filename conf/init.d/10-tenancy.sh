#!/usr/bin/env bash
set -euo pipefail

echo "Registering public tenant domains"
python /opt/portal/register_tenants.py

echo "Harvesting apps into tenant schemas"
python /opt/portal/harvest_tenants.py

echo "Applying site settings to tenant schemas"
python /opt/portal/site_tenants.py

# Tethys opens a connection with no dbname to run CREATE DATABASE, and libpq then defaults the
# dbname to the username. Point those at the portal database so they resolve whatever role connects.
export PGDATABASE="${PGDATABASE:-${TETHYS_DB_NAME:-tethys_platform}}"

echo "Provisioning isolated persistent stores per tenant"
python /opt/portal/provision_tenant_store.py

echo "Syncing persistent stores in every tenant schema"
tethys manage all_tenants_command syncstores all 2>&1 | tee /tmp/syncstores.log
if grep -qiE "error|traceback|insufficient permissions" /tmp/syncstores.log; then
  echo "FATAL: syncstores reported a failure, and tethys manage always exits 0" >&2
  exit 1
fi
