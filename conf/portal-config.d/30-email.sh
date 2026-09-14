#!/usr/bin/env bash
set -euo pipefail

if [ -z "${EMAIL_HOST:-}" ]; then
  echo "no EMAIL_HOST set, portal mail stays unconfigured"
  echo "password reset will return 302 and send nothing, see the readme" >&2
  exit 0
fi

for v in EMAIL_HOST_USER EMAIL_HOST_PASSWORD DEFAULT_FROM_EMAIL; do
  if [ -z "${!v:-}" ]; then
    echo "FATAL: EMAIL_HOST is set but $v is empty" >&2
    echo "a half configured backend fails at send time, which Django reports to the user as success" >&2
    exit 1
  fi
done

tethys settings \
  --set EMAIL_BACKEND django.core.mail.backends.smtp.EmailBackend \
  --set EMAIL_HOST "$EMAIL_HOST" \
  --set EMAIL_PORT "${EMAIL_PORT:-587}" \
  --set EMAIL_USE_TLS true \
  --set EMAIL_HOST_USER "$EMAIL_HOST_USER" \
  --set EMAIL_HOST_PASSWORD "$EMAIL_HOST_PASSWORD" \
  --set DEFAULT_FROM_EMAIL "$DEFAULT_FROM_EMAIL" \
  --set SERVER_EMAIL "$DEFAULT_FROM_EMAIL"

tethys settings -g EMAIL_BACKEND 2>/dev/null | grep -q smtp || {
  echo "FATAL: mail backend was not applied" >&2
  exit 1
}
echo "portal mail: host=$EMAIL_HOST from=$DEFAULT_FROM_EMAIL"
