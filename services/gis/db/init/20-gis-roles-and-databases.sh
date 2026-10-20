#!/usr/bin/env bash
# Runs once, when the PostGIS container initialises an empty data directory
# (after the image's own 10_postgis.sh). It creates:
#
#   * GIS_DB_MIGRATOR_USER  - owns the GIS databases and schemas; used only by Alembic
#   * GIS_DB_APP_USER       - least-privilege runtime login for the API (no DDL, no BYPASSRLS)
#   * GIS_DB_NAME           - the service database, with PostGIS installed by the superuser
#   * GIS_TEST_DB_NAME      - optional database for the integration test suite
#
# The databases are created from template0 so they do not inherit the tiger geocoder and
# topology extensions the image installs into its default database.
#
# Works whether the entrypoint executes or sources this file (so no `set -u` and no reliance on
# the entrypoint's helper functions).
set -Eeo pipefail

: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${GIS_DB_NAME:?GIS_DB_NAME must be set}"
: "${GIS_DB_MIGRATOR_USER:?GIS_DB_MIGRATOR_USER must be set}"
: "${GIS_DB_MIGRATOR_PASSWORD:?GIS_DB_MIGRATOR_PASSWORD must be set}"
: "${GIS_DB_APP_USER:?GIS_DB_APP_USER must be set}"
: "${GIS_DB_APP_PASSWORD:?GIS_DB_APP_PASSWORD must be set}"

for secret_name in POSTGRES_PASSWORD GIS_DB_MIGRATOR_PASSWORD GIS_DB_APP_PASSWORD; do
    if [ "${!secret_name:-}" = "CHANGE_ME" ]; then
        echo "gis-init: ${secret_name} still has the placeholder value from .env.example; set a real password" >&2
        exit 1
    fi
done
if [ "$GIS_DB_APP_USER" = "$GIS_DB_MIGRATOR_USER" ]; then
    echo "gis-init: GIS_DB_APP_USER and GIS_DB_MIGRATOR_USER must be different logins" >&2
    exit 1
fi

gis_psql() {
    psql -v ON_ERROR_STOP=1 --no-psqlrc --username "$POSTGRES_USER" "$@"
}

echo "gis-init: creating roles ${GIS_DB_MIGRATOR_USER} and ${GIS_DB_APP_USER}"
gis_psql --dbname postgres \
    --set=migrator_user="$GIS_DB_MIGRATOR_USER" \
    --set=migrator_password="$GIS_DB_MIGRATOR_PASSWORD" \
    --set=app_user="$GIS_DB_APP_USER" \
    --set=app_password="$GIS_DB_APP_PASSWORD" <<'SQL'
SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
    :'migrator_user', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator_user')
\gexec
SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT',
    :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec
SQL

create_gis_database() {
    local db_name="$1"
    echo "gis-init: creating database ${db_name} (owner ${GIS_DB_MIGRATOR_USER})"
    gis_psql --dbname postgres \
        --set=db_name="$db_name" \
        --set=migrator_user="$GIS_DB_MIGRATOR_USER" \
        --set=app_user="$GIS_DB_APP_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0 ENCODING %L', :'db_name', :'migrator_user', 'UTF8')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db_name', :'app_user') \gexec
SQL

    # PostGIS is not a trusted extension, so the superuser installs it; migrations then only verify it.
    gis_psql --dbname "$db_name" --set=migrator_user="$GIS_DB_MIGRATOR_USER" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT CREATE ON SCHEMA public TO %I', :'migrator_user') \gexec
SQL

    # Spatial indexes on tables with row-level security (ops.*, geo.*): see db/admin/postgis-leakproof.sql.
    gis_psql --dbname "$db_name" <<'SQL'
ALTER FUNCTION public.geometry_overlaps(public.geometry, public.geometry) LEAKPROOF;
SQL
}

create_gis_database "$GIS_DB_NAME"
if [ -n "${GIS_TEST_DB_NAME:-}" ]; then
    create_gis_database "$GIS_TEST_DB_NAME"
fi

echo "gis-init: done"
