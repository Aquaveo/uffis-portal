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

RUN git clone --depth 1 https://github.com/tethysplatform/tethysapp-tethys_dash.git \
      "${TETHYS_APPS_ROOT}/tethysdash" \
  && mv "${DEV_REACT_CONFIG}" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_DEBUG_MODE.*#TETHYS_DEBUG_MODE = ${TETHYS_DEBUG_MODE}#g" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_LOADER_DELAY.*#TETHYS_LOADER_DELAY = ${TETHYS_LOADER_DELAY}#g" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_PORTAL_HOST.*#TETHYS_PORTAL_HOST = ${TETHYS_PORTAL_HOST}#g" "${PROD_REACT_CONFIG}" \
  && sed -i "s#TETHYS_APP_ROOT_URL.*#TETHYS_APP_ROOT_URL = ${TETHYS_APP_ROOT_URL}#g" "${PROD_REACT_CONFIG}" \
  && ( cd "${TETHYS_APPS_ROOT}/tethysdash" && npm install && npm run build ) \
  && uv pip install --no-cache "${TETHYS_APPS_ROOT}/tethysdash"

RUN chmod -R a+rX /opt/python /opt/conda \
  && chmod -R a+rwX /opt/conda/envs/tethys/lib/python3.12/site-packages/tethysapp/tethysdash

FROM ${BASE}:${BASE_TAG} AS runtime

COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/conda  /opt/conda

COPY --chown=1000:1000 conf/portal_config.yml /config/portal_config.yml
COPY --chmod=0755 conf/portal-config.d/ /opt/portal/portal-config.d/
COPY --chmod=0755 conf/init.d/ /opt/portal/init.d/
COPY conf/portal_storage.py conf/register_tenants.py conf/harvest_tenants.py conf/site_tenants.py conf/provision_tenant_store.py /opt/portal/
