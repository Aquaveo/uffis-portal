# syntax=docker/dockerfile:1
ARG BASE=ghcr.io/aquaveo/tethys-uvx
ARG BASE_BUILDER=builder-1505870
ARG BASE_TAG=runtime-base-1505870

FROM ${BASE}:${BASE_BUILDER} AS builder

WORKDIR ${TETHYS_HOME}

COPY pyproject.toml .
RUN uv pip install --no-cache -r pyproject.toml

RUN chmod -R a+rX /opt/python /opt/conda

FROM ${BASE}:${BASE_TAG} AS runtime

COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/conda  /opt/conda

COPY --chown=1000:1000 conf/portal_config.yml /config/portal_config.yml
COPY --chmod=0755 conf/portal-config.d/ /opt/portal/portal-config.d/
COPY --chmod=0755 conf/init.d/ /opt/portal/init.d/
COPY conf/portal_storage.py conf/register_tenants.py conf/harvest_tenants.py \
     conf/site_tenants.py /opt/portal/
