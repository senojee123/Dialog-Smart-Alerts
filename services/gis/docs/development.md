# Local development guide

From a fresh clone to the map showing reference data, a tenant's objects and enriched events, then the
everyday loop. For what each part is, see [ARCHITECTURE.md](../ARCHITECTURE.md); for tests,
[testing.md](testing.md).

## 1. Prerequisites

* Docker Desktop or Docker Engine with Compose v2 (the whole stack runs in containers), **or**
  PostgreSQL 18 + PostGIS 3.6, Python 3.13 and Node 24 on the host.
* For the command-line tools and tests on the host: Python 3.13 (`backend/requirements-dev.lock`).
  Exactly 3.13: a newer default `python` is refused by `pip install -e .`. On Windows create the
  environment with `py -3.13 -m venv .venv` (install 3.13 with `winget install -e --id
  Python.Python.3.13` if `py -0p` does not list it).
* Optional: `gdal-bin` ≥ 3.8 and the `pipeline` extra, only to rebuild reference data from sources.

## 2. Start the stack

The GIS runs as the main platform's GIS instance: it checks no credentials, and requests act for the
platform's organisation (`GIS_TENANT_ID`, default `dialog-smart-alerts`) unless they name another tenant
in `X-GIS-Tenant-Id`. Nothing to issue and nothing that expires.

```bash
.\setup.ps1 -WithSampleTenant      # Windows; or: bash setup.sh --with-sample-tenant
```

or by hand:

```bash
cp .env.example .env               # set the three CHANGE_ME passwords (README, Quick start)
docker compose up --build -d                            # db -> migrate (registers GIS_TENANT_ID) -> api -> web
docker compose --profile sample run --rm sample-data    # reference data, basemap, sample tenant, events
curl -s localhost:8100/health/ready                     # "status": "ready"
```

`sample-data` loads the release `ref-2026.09-dev` from `data/sample/` (with its basemap from
`data/basemap/ref-2026.09-dev` when present), runs the reference data QA and makes it current, registers
the tenant `wildlife-dept` and creates its 5 sites, 6 devices, 3 geofences and 10 events through the
services ([../data/sample/README.md](../data/sample/README.md)). Running it again adds a new batch of
events for the last 24 hours and changes nothing else. With `-e GIS_SAMPLE_TENANT_DATA=false` it loads
the release and basemap only.

## 3. Open the map

Open <http://localhost:5174>. It shows the platform's organisation; to look at the sample tenant, name it
for the map:

```dotenv
# frontend/.env.local (git-ignored)
VITE_TENANT_ID=wildlife-dept
```

Restart the web container (`docker compose restart web`). The status button says **Service ready**; the
map shows the basemap, the reference layers, the tenant's devices, fields of view, geofences and events.
A view can be linked: `http://localhost:5174/#map=13/8.04/80.76` opens at zoom 13 over Habarana.

## 4. Send an event

Events come from the main platform's event processing:

```bash
curl -s -X POST localhost:8100/geo/v1/enrich -H "X-GIS-Tenant-Id: wildlife-dept"   -H "Content-Type: application/json" -d '{
    "eventId": "dev-evt-1", "tenantId": "wildlife-dept",
    "observedAt": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
    "eventType": "wildlife.elephant_detected", "sourceType": "sensor", "locationSource": "sensor",
    "location": {"type": "Point", "coordinates": [80.8652, 8.0492]}}'
```

The answer is the geo-context (administrative areas, nearest settlement and road, Minneriya National Park,
the corridor geofence, nearby devices). Press **Reload** in the event filters to see the event on the
map, and click it.

## 5. Without containers

```bash
docker compose up -d db                                   # or your own PostgreSQL + PostGIS
cd backend
export GIS_DB_HOST=localhost GIS_DB_PORT=5434 GIS_DB_APP_PASSWORD=... GIS_DB_MIGRATOR_PASSWORD=...
alembic -c ../db/alembic.ini upgrade head
python -m app.tools.register_tenant                       # GIS_TENANT_ID
python -m app.pipeline load ../data/sample/ref-2026.09-dev --basemap ../data/basemap/ref-2026.09-dev --current
python -m app.tools.seed_dev_data ../data/sample/operational/wildlife-dept.json
uvicorn app.main:create_app --factory --reload --port 8100
cd ../frontend && npm ci && GIS_API_PROXY_TARGET=http://localhost:8100 npm run dev -- --port 5174
```

A database you create yourself needs the PostGIS `&&` operator marked LEAKPROOF so row-level security can
use spatial indexes: `psql -U postgres -d gis -f db/admin/postgis-leakproof.sql` (the container does it on
first start). Without it everything is correct but tenant-table lookups slow down with volume
([performance.md](performance.md)).

## 6. Everyday loop

| Task | Command |
|---|---|
| Backend with reload | the `api` service reloads `backend/app`; or `uvicorn ... --reload` |
| Web client with hot reload | the `web` service; or `npm run dev` |
| New migration | `cd backend && alembic -c ../db/alembic.ini revision -m "..." --rev-id YYYYMMDD_NNNN`, then update the ORM models and `python ../db/tools/generate_schema_docs.py` |
| Tests | [testing.md](testing.md) |
| Lint and types | `ruff check . ../db ../data`, `ruff format`, `mypy app ../db/migrations ../db/tools tests`; `npm run lint`, `npm run typecheck` (never run prettier on the frontend) |
| Rebuild reference data from sources | `python -m app.pipeline run --profile ../data/pipeline/profiles/dev.toml --basemap --current` ([reference-data/pipeline.md](reference-data/pipeline.md)) |
| Measure latency and plans | `python -m app.tools.benchmark` ([performance.md](performance.md)) |
| Browser end-to-end tests | `npm run e2e` ([testing.md](testing.md#browser-end-to-end-tests)) |
| Start over | `docker compose down -v` (deletes the database volume) |

## 7. When something is off

| Symptom | Look at |
|---|---|
| `/health/ready` not ready | the failing check in its answer; `docker compose logs migrate api` |
| 403 `tenant_not_registered` | the tenant the request acts for is not registered: `docker compose run --rm migrate` (for `GIS_TENANT_ID`) or `python -m app.tools.register_tenant --tenant <id>` |
| Map without basemap | `data/basemap/ref-2026.09-dev` present, `VITE_BASEMAP_STYLE_URL` set (default in `.env.example`) |
| Map without reference layers | no current release: run `sample-data` |
| No events on the map | the event window (24 h by default) and the tenant (`VITE_TENANT_ID`); events from `sample-data` are relative to when it ran |

More in the README's troubleshooting table.
