#!/usr/bin/env bash
set -euo pipefail

if [ "${TETHYS_DB_POOL_MODE:-direct}" != "direct" ]; then
  echo "FATAL: multi tenancy requires TETHYS_DB_POOL_MODE=direct" >&2
  echo "a transaction mode pooler multiplexes SET search_path across tenants" >&2
  exit 1
fi

tethys settings --set DATABASES.default.ENGINE django_tenants.postgresql_backend

tethys settings -g DATABASES.default.ENGINE 2>/dev/null | grep -q django_tenants || {
  echo "FATAL: tenancy engine was not applied" >&2
  exit 1
}
