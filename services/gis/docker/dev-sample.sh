#!/bin/sh
# Load the development sample into the local database (docker compose --profile sample run --rm sample-data):
#
#   1. the reference data release data/sample/<release> - with its basemap from data/basemap/<release>
#      when that has been built or delivered - checked by the database QA and made current;
#   2. the sample tenant's sites, devices, geofences and a batch of enriched events
#      (data/sample/operational/wildlife-dept.json, python -m app.tools.seed_dev_data);
#      skipped with GIS_SAMPLE_TENANT_DATA=false (the main platform brings its own devices).
#
# Safe to run again: a release that is already loaded is left alone, the tenant's objects are matched by
# their identifiers, and each run adds one batch of events for the last 24 hours. Refuses GIS_ENV=production.
set -eu

RELEASE="${GIS_SAMPLE_RELEASE:-ref-2026.09-dev}"
SAMPLE=/srv/data/sample
BASEMAP="/srv/data/basemap/$RELEASE"

if python -m app.pipeline status "$RELEASE" >/dev/null 2>&1; then
    echo "reference data release $RELEASE is already loaded" >&2
else
    if [ -f "$BASEMAP/artifacts.json" ]; then
        python -m app.pipeline --actor dev-sample load "$SAMPLE/$RELEASE" --basemap "$BASEMAP" --current
    else
        echo "no basemap in data/basemap/$RELEASE: the map will use the neutral background" >&2
        python -m app.pipeline --actor dev-sample load "$SAMPLE/$RELEASE" --current
    fi
fi
if [ "${GIS_SAMPLE_TENANT_DATA:-true}" = "false" ]; then
    echo "GIS_SAMPLE_TENANT_DATA=false: the sample tenant's objects and events are not loaded" >&2
else
    python -m app.tools.seed_dev_data "$SAMPLE/operational/wildlife-dept.json"
fi
