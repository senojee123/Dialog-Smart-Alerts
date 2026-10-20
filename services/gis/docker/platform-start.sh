#!/bin/sh
# Start the GIS service as the main platform deploys it (the `platform` image target).
#
#   GIS_RUN_MIGRATIONS=true         migrate to head and register GIS_TENANT_ID first (needs
#                                   GIS_DB_MIGRATOR_PASSWORD); use it when the platform has no separate
#                                   migration job (e.g. Railway's start or pre-deploy command)
#   GIS_LOAD_SAMPLE_REFERENCE=true  also load the development reference data release and make it current,
#                                   when it is not loaded yet (refused with GIS_ENV=production)
#   PORT                            the port to listen on (default 8000; Railway sets it)
set -eu

RELEASE="${GIS_SAMPLE_RELEASE:-ref-2026.09-dev}"

if [ "${GIS_RUN_MIGRATIONS:-false}" = "true" ]; then
    alembic -c /srv/db/alembic.ini upgrade head
    python -m app.tools.register_tenant
    if [ "${GIS_LOAD_SAMPLE_REFERENCE:-false}" = "true" ]; then
        if python -m app.pipeline status "$RELEASE" >/dev/null 2>&1; then
            echo "reference data release $RELEASE is already loaded" >&2
        else
            GIS_DB_IDLE_IN_TRANSACTION_TIMEOUT_MS=600000 python -m app.pipeline --actor platform-start \
                load "/srv/data/sample/$RELEASE" --basemap "/srv/basemap/$RELEASE" --current
        fi
    fi
fi

exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
    --no-access-log --no-server-header
