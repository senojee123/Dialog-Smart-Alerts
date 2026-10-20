#!/usr/bin/env bash
# Start the GIS Core Service (the main platform's GIS instance) locally with one command (Linux, macOS,
# WSL). Needs Docker with Compose v2.
#
#   bash setup.sh                     # or: --skip-sample-data, --with-sample-tenant
#
# Safe to run again at any time; each step only does what is still missing:
#   1. .env              created from .env.example with random passwords
#   2. images + stack    docker compose build, then db -> migrate (registers GIS_TENANT_ID) -> api -> web
#   3. reference data    the development release and basemap, loaded once and made current
#                        (--with-sample-tenant: also the demonstration tenant wildlife-dept and its events)
# The GIS checks no credentials: the main platform owns users and sign-in. Windows: use setup.ps1 / setup.cmd.
set -euo pipefail
cd "$(dirname "$0")"

SKIP_SAMPLE=false
SAMPLE_TENANT=false
for arg in "$@"; do
  case "$arg" in
    --skip-sample-data) SKIP_SAMPLE=true ;;
    --with-sample-tenant) SAMPLE_TENANT=true ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
die() { printf '\033[31mError: %s\033[0m\n' "$1" >&2; exit 1; }

new_password() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true; }

# get_value FILE NAME [DEFAULT]
get_value() {
  local value
  value=$(grep -E "^$2=" "$1" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)
  printf '%s' "${value:-${3:-}}"
}

# set_value FILE NAME VALUE: replaces the line, or appends it (portable: no sed -i).
set_value() {
  local tmp
  tmp=$(mktemp)
  if grep -qE "^$2=" "$1" 2>/dev/null; then
    awk -v name="$2" -v value="$3" 'index($0, name "=") == 1 { print name "=" value; next } { print }' "$1" >"$tmp"
  else
    { [ -f "$1" ] && cat "$1"; printf '%s=%s\n' "$2" "$3"; } >"$tmp"
  fi
  cat "$tmp" >"$1"
  rm -f "$tmp"
}

# ---------------------------------------------------------------------------------------------------------
step "Checking Docker"
command -v docker >/dev/null 2>&1 || die "Docker is not installed (https://docs.docker.com/get-docker/)."
docker info >/dev/null 2>&1 || die "Docker is not running, or this user may not use it. Start Docker and try again."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 ('docker compose') is missing."
echo "Docker is running."

# ---------------------------------------------------------------------------------------------------------
step "Configuration (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
else
  echo "Using the existing .env."
fi
for name in POSTGRES_SUPERUSER_PASSWORD GIS_DB_MIGRATOR_PASSWORD GIS_DB_APP_PASSWORD; do
  value=$(get_value .env "$name")
  if [ -z "$value" ] || [ "$value" = "CHANGE_ME" ]; then
    set_value .env "$name" "$(new_password)"
    echo "  $name set to a new random password."
  elif printf '%s' "$value" | grep -q '[^A-Za-z0-9]'; then
    echo "  Warning: $name contains characters other than letters and digits; Docker Compose may change it."
  fi
done
api_port=$(get_value .env GIS_API_HOST_PORT 8100)
web_port=$(get_value .env GIS_WEB_HOST_PORT 5174)

# ---------------------------------------------------------------------------------------------------------
step "Building images (the first time this downloads packages and takes several minutes)"
docker compose build

# ---------------------------------------------------------------------------------------------------------
step "Map client settings (frontend/.env.local)"
touch frontend/.env.local
if grep -qE '^VITE_BASEMAP_STYLE_URL=' frontend/.env.local; then
  echo "Using the existing frontend/.env.local."
else
  set_value frontend/.env.local VITE_BASEMAP_STYLE_URL /basemap/ref-2026.09-dev/style.json
  echo "Basemap set to the development release."
fi

# ---------------------------------------------------------------------------------------------------------
step "Starting the stack (db -> migrate -> api -> web)"
docker compose up -d

echo "Waiting for http://localhost:$api_port/health/ready ..."
ready=false
for _ in $(seq 1 120); do
  if curl -fsS -m 10 "http://localhost:$api_port/health/ready" >/dev/null 2>&1; then ready=true; break; fi
  sleep 5
done
$ready || die "The API did not become ready within 10 minutes. See: docker compose logs migrate api"
echo "API is ready."

# ---------------------------------------------------------------------------------------------------------
if ! $SKIP_SAMPLE; then
  step "Development reference data"
  current=$(echo "SELECT count(*) FROM meta.ref_data_release WHERE is_current;" |
    docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$GIS_DB_NAME" -At' 2>/dev/null | tr -d '\r' || true)
  if [ "$current" = "1" ] && ! $SAMPLE_TENANT; then
    echo "Already loaded (a reference data release is current)."
  else
    echo "Loading the development sample (a few minutes)..."
    mkdir -p .local
    docker compose --profile sample run --rm -T -e "GIS_SAMPLE_TENANT_DATA=$SAMPLE_TENANT" sample-data >.local/sample-data.log
    echo "Loaded. Details: .local/sample-data.log"
  fi
fi

printf '\n\033[32mGIS Core Service is running.\033[0m\n'
echo "  Map client   http://localhost:$web_port   (first load can take ~20 s)"
echo "  Yala / B43   http://localhost:$web_port/#map=11/6.38/81.45"
echo "  API docs     http://localhost:$api_port/docs"
echo "  Readiness    http://localhost:$api_port/health/ready"
echo
echo "Stop: docker compose down"
