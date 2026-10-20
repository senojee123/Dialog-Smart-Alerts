# syntax=docker/dockerfile:1
#
# GIS Core Service backend image.
#
# Targets:
#   runtime   API and migration job (non-root, hash-pinned dependencies)
#   test      runtime + test tooling, the test suite and data/fixtures (`docker compose --profile test`)
#   pipeline  runtime + GDAL command-line tools, GeoPandas and pyogrio: the reference data pipeline
#             (`docker compose --profile pipeline run --rm pipeline <command>`); data/ is mounted at /srv/data
#   platform  (default) runtime + the built map application (/app), the basemaps (/basemap) and the
#             development reference data release: the one GIS service the main platform deploys and
#             proxies (docker/platform-start.sh migrates and loads reference data when asked to)
#
# Build from this folder (services/gis):
#   docker build -f docker/backend.Dockerfile --target runtime -t gis-core-service-backend .
#   docker build -f docker/backend.Dockerfile -t dialog-gis .

# Debian trixie: its gdal-bin (3.10) has the PMTiles and MVT drivers the basemap needs (GDAL >= 3.8).
ARG PYTHON_IMAGE=python:3.13-slim-trixie
ARG NODE_IMAGE=node:24-slim

FROM ${PYTHON_IMAGE} AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv

# Third-party dependencies only, verified against the hashes in the lock file.
FROM python-base AS runtime-deps
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements.lock

# Build the application wheel (so package metadata such as the version is available at runtime).
FROM runtime-deps AS build
COPY backend/pyproject.toml /src/backend/pyproject.toml
COPY backend/app /src/backend/app
RUN pip wheel --no-deps --wheel-dir /wheels /src/backend

FROM runtime-deps AS runtime
RUN groupadd --system --gid 10001 gis \
    && useradd --system --uid 10001 --gid gis --home-dir /srv --no-create-home --shell /usr/sbin/nologin gis
COPY --from=build /wheels /wheels
RUN pip install --no-deps /wheels/*.whl && rm -rf /wheels
WORKDIR /srv
COPY db/alembic.ini /srv/db/alembic.ini
COPY db/migrations /srv/db/migrations
ENV GIS_ALEMBIC_CONFIG_PATH=/srv/db/alembic.ini
USER gis
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--no-server-header"]

FROM runtime AS test
USER root
COPY backend/requirements-dev.lock /tmp/requirements-dev.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements-dev.lock
COPY --chown=gis:gis backend /srv/backend
COPY --chown=gis:gis data/fixtures /srv/data/fixtures
COPY --chown=gis:gis data/sample /srv/data/sample
COPY --chown=gis:gis data/pipeline /srv/data/pipeline
USER gis
WORKDIR /srv/backend
ENV PYTHONPATH=/srv/backend
CMD ["pytest"]

FROM runtime AS pipeline
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-pipeline.lock /tmp/requirements-pipeline.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements-pipeline.lock
COPY --chown=gis:gis backend /srv/backend
USER gis
WORKDIR /srv/backend
# The source tree layout (/srv/backend/app, /srv/data) is what the pipeline's default directories assume.
ENV PYTHONPATH=/srv/backend \
    GIS_REQUIRE_PIPELINE=1
ENTRYPOINT ["python", "-m", "app.pipeline"]
CMD ["--help"]

# The map application, built for the main platform: served at /gis-app/, calling the API through the
# platform's proxy (/api/gis), with the offline basemap first and OpenStreetMap's online tiles second.
FROM ${NODE_IMAGE} AS web-build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV GIS_WEB_BASE=/gis-app/     VITE_API_BASE_URL=/api/gis     VITE_BASEMAPS='[{"id":"basemap","label":"Sri Lanka (offline)","styleUrl":"/basemap/ref-2026.09-dev/style.json"},{"id":"osm","label":"OpenStreetMap (online)","styleUrl":"/gis-app/basemaps/osm-standard.json"}]'
RUN npm run build

FROM runtime AS platform
COPY --from=web-build --chown=gis:gis /web/dist /srv/web
COPY --chown=gis:gis data/basemap /srv/basemap
COPY --chown=gis:gis data/sample /srv/data/sample
COPY --chown=gis:gis docker/platform-start.sh /srv/platform-start.sh
ENV GIS_WEB_DIR=/srv/web     GIS_BASEMAP_DIR=/srv/basemap
CMD ["sh", "/srv/platform-start.sh"]
