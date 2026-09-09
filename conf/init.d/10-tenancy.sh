#!/usr/bin/env bash
set -euo pipefail

echo "Registering public tenant domains"
python /opt/portal/register_tenants.py

echo "Harvesting apps into tenant schemas"
python /opt/portal/harvest_tenants.py

echo "Applying site settings to tenant schemas"
python /opt/portal/site_tenants.py
