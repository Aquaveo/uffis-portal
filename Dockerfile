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

ARG TETHYSDASH_REF=39e664b9e02539439ed96f5d687ed765c36bfaf2
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

ARG WMO_PLUGINS_REF=aeff0ac15d872d161e6984dbd15eace9eb07dba5
RUN uv pip install --no-cache \
      "tgf-wmo-plugins @ git+https://github.com/Aquaveo/tgf_wmo_plugins.git@${WMO_PLUGINS_REF}"

RUN chmod -R a+rX /opt/python /opt/conda \
  && chmod -R a+rwX /opt/conda/envs/tethys/lib/python3.12/site-packages/tethysapp/tethysdash

FROM ${BASE}:${BASE_TAG} AS runtime

COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/conda  /opt/conda

COPY --chown=1000:1000 conf/portal_config.yml /config/portal_config.yml
COPY --chmod=0755 conf/portal-config.d/ /opt/portal/portal-config.d/
COPY --chmod=0755 conf/init.d/ /opt/portal/init.d/
COPY conf/portal_storage.py conf/email_settings.py conf/portal_context.py conf/account_requests.py conf/access_groups.py conf/csrf_failure.py conf/public_gate.py conf/register_tenants.py conf/harvest_tenants.py conf/site_tenants.py conf/provision_tenant_store.py /opt/portal/
COPY conf/portal_templates/ /opt/portal/portal_templates/
