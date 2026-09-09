#!/usr/bin/env bash
set -euo pipefail

echo "Registering public tenant domains"
python /opt/portal/register_tenants.py
