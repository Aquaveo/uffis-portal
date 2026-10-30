# syntax=docker/dockerfile:1
ARG BASE=ghcr.io/aquaveo/tethys-uvx
ARG BASE_BUILDER=builder-1505870
ARG BASE_TAG=runtime-base-1505870

FROM ${BASE}:${BASE_BUILDER} AS builder

WORKDIR ${TETHYS_HOME}

COPY pyproject.toml .
RUN uv pip install --no-cache -r pyproject.toml

ARG TETHYS_PORTAL_HOST=""
ARG TETHYS_APP_ROOT_URL="/apps/tethysdash/"
ARG TETHYS_LOADER_DELAY="500"
ARG TETHYS_DEBUG_MODE="false"
ENV DEV_REACT_CONFIG="${TETHYS_APPS_ROOT}/tethysdash/reactapp/config/development.env" \
    PROD_REACT_CONFIG="${TETHYS_APPS_ROOT}/tethysdash/reactapp/config/production.env"

ARG TETHYSDASH_REF=148f62d5d971a44790afbcafb160dcc61bf05ddd
RUN git clone https://github.com/tethysplatform/tethysapp-tethys_dash.git \
      "${TETHYS_APPS_ROOT}/tethysdash" \
  && git -C "${TETHYS_APPS_ROOT}/tethysdash" checkout --detach "${TETHYSDASH_REF}" \
  && mv "${DEV_REACT_CONFIG}" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_DEBUG_MODE.*#TETHYS_DEBUG_MODE = ${TETHYS_DEBUG_MODE}#g" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_LOADER_DELAY.*#TETHYS_LOADER_DELAY = ${TETHYS_LOADER_DELAY}#g" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_PORTAL_HOST.*#TETHYS_PORTAL_HOST = ${TETHYS_PORTAL_HOST}#g" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_APP_ROOT_URL.*#TETHYS_APP_ROOT_URL = ${TETHYS_APP_ROOT_URL}#g" "${PROD_REACT_CONFIG}" \
  && ( cd "${TETHYS_APPS_ROOT}/tethysdash" && npm install && npm run build ) \
  && uv pip install --no-cache "${TETHYS_APPS_ROOT}/tethysdash"

ARG WMO_PLUGINS_REF=25bec25233a8be5c5d68e571a01a9f1159fef706
RUN uv pip install --no-cache \
      "tgf-wmo-plugins @ git+https://github.com/Aquaveo/tgf_wmo_plugins.git@${WMO_PLUGINS_REF}"

ARG UFFIS_FORECASTS_REF=536a611ff77cbf50398d78f4976e80b715c1195c
RUN uv pip install --no-cache \
      "tethysapp-uffis_forecasts @ git+https://github.com/Aquaveo/tethysapp-uffis_forecasts.git@${UFFIS_FORECASTS_REF}"

# Compile translations; incomplete ones fail
RUN apt-get update && apt-get install -y --no-install-recommends gettext && rm -rf /var/lib/apt/lists/*
COPY conf/locale /opt/portal/locale
RUN set -e; \
    for po in /opt/portal/locale/*/LC_MESSAGES/*.po \
              /opt/conda/envs/tethys/lib/python3.*/site-packages/tethysapp/uffis_forecasts/locale/*/LC_MESSAGES/*.po; do \
      msgfmt --check --statistics -o "${po%.po}.mo" "$po" 2> /tmp/msgfmt.log; cat /tmp/msgfmt.log; \
      if grep -qE "untranslated|fuzzy" /tmp/msgfmt.log; then echo "incomplete translation: $po" >&2; exit 1; fi; \
    done

RUN chmod -R a+rX /opt/python /opt/conda \
  && chmod -R a+rwX /opt/conda/envs/tethys/lib/python3.12/site-packages/tethysapp/tethysdash

FROM ${BASE}:${BASE_TAG} AS runtime

COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/conda  /opt/conda

COPY --chown=1000:1000 conf/portal_config.yml /config/portal_config.yml
COPY --chmod=0755 conf/portal-config.d/ /opt/portal/portal-config.d/
COPY --chmod=0755 conf/init.d/ /opt/portal/init.d/
COPY conf/agencies.py conf/apex_apps.py conf/apex_locale.py conf/i18n_settings.py conf/apex_urls.py conf/portal_storage.py conf/email_settings.py conf/portal_context.py conf/account_requests.py conf/access_groups.py conf/csrf_failure.py conf/public_gate.py conf/register_tenants.py conf/harvest_tenants.py conf/site_tenants.py conf/provision_tenant_store.py /opt/portal/
COPY conf/portal_templates/ /opt/portal/portal_templates/
COPY --from=builder /opt/portal/locale /opt/portal/locale
COPY conf/paused_tenants.py /opt/portal/
