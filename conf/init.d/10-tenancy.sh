#!/usr/bin/env bash
set -euo pipefail

echo "Migrating tenant schemas"
tethys manage migrate_schemas

echo "Registering public tenant domains"
python /opt/portal/register_tenants.py

echo "Harvesting apps into tenant schemas"
python /opt/portal/harvest_tenants.py
