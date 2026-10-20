# GIS Core Service

Geospatial intelligence for the geo-aware event intelligence platform in Sri Lanka:

* PostgreSQL + PostGIS as the authoritative spatial store
* geo-context enrichment of events
* spatial query APIs
* geofence and site/device placement management
* a React + MapLibre map component

**Part of the main platform.** This folder is the GIS instance of Dialog Smart Alerts (`services/gis` in
the platform's repository). The platform owns users and sign-in, so the GIS checks no credentials: it is
reached only through the platform, and every request acts for the platform's organisation
(`GIS_TENANT_ID`), or for the tenant named in the `X-GIS-Tenant-Id` header. See
[docs/integration.md](docs/integration.md) and [ADR-0019](docs/adr/ADR-0019-platform-instance-without-own-authentication.md).

**Boundary.** This service produces spatial facts only. It does not send alerts, choose notification
recipients, store user notification locations or deliver messages. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full boundary, the architecture and the design decisions.

> **Status: MVP candidate (0.1.0), validated in development - not production-ready.** The authoritative
> PostGIS data model with row-level security, geo-context enrichment (`POST /geo/v1/enrich`), the spatial
> query API, geofence, site and device placement management, the reference data pipeline and releases,
> and the embeddable MapLibre map client are implemented and pass 1 068 backend and 323 frontend tests
> (version 2, inside the platform; see [docs/integration-details.md](docs/integration-details.md#8-tests)). What production still needs (load tests, official datasets under agreement,
> operations) is in the [validation report](docs/validation.md).

| Guide | |
|---|---|
| [Local development](docs/development.md) | From a fresh clone to the map with sample data |
| [API reference](docs/api/README.md) | Every endpoint, its permission and its documentation |
| [Test guide](docs/testing.md) | Suites, commands, the end-to-end scenario and the boundary cases |
| [Performance](docs/performance.md) | Latency, query plans and index decisions |
| [Validation report](docs/validation.md) | What was validated, defects fixed, what is not production-ready |
| [Boundary audit](docs/boundary-audit.md) | No alerting, notification or recipient functionality, checked |

---

## Repository layout

```
gis-core-service/
├── backend/                 FastAPI service (Python 3.13)
│   ├── app/
│   │   ├── api/             routers, dependency wiring, the caller, error handlers  (/health, /geo/v1)
│   │   ├── core/            settings, logging, middleware, errors, tenancy, the caller
│   │   ├── db/              async engine, transactional sessions, declarative base
│   │   ├── models/          ORM models (mirror the migrations)
│   │   ├── repositories/    parameterised SQL (spatial lookups, queries, operational, events)
│   │   ├── schemas/         Pydantic models (GeoJSON, events, geo-context, queries, problems)
│   │   ├── services/        use cases (readiness, reference data loading, QA and releases,
│   │   │                    enrichment/ engine, spatial_query, operational)
│   │   ├── pipeline/        reference data pipeline: profiles, acquisition, CRS, adapters (vector, OSM),
│   │   │                    file QA, release build, basemap (python -m app.pipeline)
│   │   ├── spatial/         CRS conventions, service area, GeoJSON validation, layer registry
│   │   ├── tools/           command-line tools (load_reference_data, seed_dev_data, register_tenant,
│   │   │                    benchmark, export_crs_reference)
│   │   └── main.py          application factory
│   ├── tests/               unit/ (no database), pipeline/ (GDAL) and integration/ (PostGIS)
│   ├── pyproject.toml
│   └── requirements*.lock   hash-pinned dependency locks
├── frontend/                React + TypeScript + MapLibre GL JS + Terra Draw (Vite)
│   ├── e2e/                 browser end-to-end tests (Playwright)
│   └── src/
│       ├── map/             the embeddable map client: layers/, controls/, tools/, editor/, popup/, state/
│       ├── geo/             EPSG:5235 projection and geometry helpers
│       ├── services/        API client and the typed endpoint functions
│       └── types/           API contracts, validated with zod
├── db/
│   ├── alembic.ini
│   ├── migrations/          Alembic environment, shared DDL helpers and revisions 0001-0008
│   ├── tools/               schema documentation generator
│   ├── admin/               superuser scripts (postgis-leakproof.sql)
│   └── init/                first-start script for the PostGIS container (roles, databases)
├── data/                    pipeline/ (profiles), sample/ (development release and tenant), fixtures/
│                            (test data); raw/, processed/, basemap/ are not versioned (data/README.md)
├── docker/                  Dockerfiles for backend (runtime, test, pipeline) and frontend; dev-sample.sh
├── docs/                    development.md, testing.md, performance.md, validation.md, boundary-audit.md,
│                            security.md, api/ (endpoint references), frontend/ (map client), database/
│                            (data model, schema reference, ERD), reference-data/ (pipeline), adr/
├── docker-compose.yml       local development stack
├── .env.example             configuration template
├── ARCHITECTURE.md
└── README.md
```

## Quick start (Docker)

Prerequisites: Docker Desktop (or Docker Engine) with Docker Compose v2.

The quickest way is one command: `.\setup.ps1` on Windows (or double-click `setup.cmd`), `bash setup.sh`
elsewhere. It creates `.env`, starts the stack and loads the development reference data. Add
`-WithSampleTenant` (`--with-sample-tenant`) for the demonstration tenant near Habarana. By hand:

1. **Create your configuration.**

   Linux, macOS or WSL:

   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # run once per password
   ```

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})   # run once per password
   ```

   Replace the three `CHANGE_ME` values in `.env` (`POSTGRES_SUPERUSER_PASSWORD`,
   `GIS_DB_MIGRATOR_PASSWORD`, `GIS_DB_APP_PASSWORD`) with different random passwords.

2. **Start the stack.**

   ```bash
   docker compose up --build
   ```

   The services start in order: `db` (PostGIS; creates logins and databases on the first run) ->
   `migrate` (Alembic, then registers the platform's organisation `GIS_TENANT_ID`, then exits) -> `api` ->
   `web`. The ports leave the main platform's 8000 and 5173 free.

3. **Open it.**

   | What | URL |
   |---|---|
   | Map client | http://localhost:5174 |
   | API docs (OpenAPI) | http://localhost:8100/docs |
   | Liveness | http://localhost:8100/health/live |
   | Readiness | http://localhost:8100/health/ready |
   | Service area (GeoJSON) | http://localhost:8100/geo/v1/service-area |
   | Geo-context enrichment | `POST` http://localhost:8100/geo/v1/enrich (see below) |
   | Layer catalogue | http://localhost:8100/geo/v1/layers |
   | Spatial queries | `POST` http://localhost:8100/geo/v1/query/within-distance, `/nearest`, `/contains` |
   | Reverse geocoding | http://localhost:8100/geo/v1/reverse?lon=80.7513&lat=8.0342 |
   | Events, geofences, sites, devices, exports, audit, releases | see the [API reference](docs/api/README.md) (29 operations) |
   | Prometheus metrics | http://localhost:8100/metrics |
   | PostgreSQL | `localhost:5434`, database `gis` |

   When everything works, the map client's status panel shows **Ready**, with passing checks for the
   database, PostGIS, coordinate systems, CRS consistency, tenant spatial indexes and schema migrations.

4. **Load the development sample** (reference data release `ref-2026.09-dev`, its basemap, and a tenant
   with sites, devices, geofences and events near Habarana; see [data/sample](data/sample/README.md)):

   ```bash
   docker compose --profile sample run --rm sample-data
   ```

   For the reference data only (the main platform brings its own devices):
   `docker compose --profile sample run --rm -e GIS_SAMPLE_TENANT_DATA=false sample-data`.

### Calling the enrichment API

`POST /geo/v1/enrich` needs reference data (above) and a registered tenant. No credentials: the request
acts for `GIS_TENANT_ID` (`dialog-smart-alerts`, registered by `migrate`), or for the tenant in the
`X-GIS-Tenant-Id` header:

```bash
curl -s -X POST http://localhost:8100/geo/v1/enrich -H "Content-Type: application/json"   -d '{"eventId":"evt-1","tenantId":"dialog-smart-alerts","observedAt":"2026-09-14T08:32:10+05:30",
       "eventType":"wildlife.elephant_detected","sourceType":"sensor","locationSource":"sensor",
       "location":{"type":"Point","coordinates":[80.749,8.037]}}'
```

The request and response members, errors and settings are described in
[docs/api/enrichment.md](docs/api/enrichment.md); the OpenAPI page (`/docs`) has runnable examples.

### Calling the spatial query API

```bash
curl -s http://localhost:8100/geo/v1/me                           # permissions and tenant
curl -s http://localhost:8100/geo/v1/layers                       # what can be queried
curl -s "http://localhost:8100/geo/v1/reverse?lon=80.7513&lat=8.0342"
curl -s "http://localhost:8100/geo/v1/layers/ref.settlement/features?bbox=80.6,7.9,80.9,8.2"
curl -s -H "X-GIS-Tenant-Id: wildlife-dept"   "http://localhost:8100/geo/v1/layers/ops.device/features?bbox=80.6,7.9,80.9,8.2"   # another tenant
curl -s -H "Content-Type: application/json"   -d '{"target":"ref.facility","geometry":{"type":"Point","coordinates":[80.7513,8.0342]},
       "distanceM":5000}'   http://localhost:8100/geo/v1/query/within-distance
```

Every endpoint, its filters, paging, the geofence shapes and the error codes are described in
[docs/api/spatial-queries.md](docs/api/spatial-queries.md).

Stop with `docker compose down`. To remove the database volume as well: `docker compose down -v`.

### Windows notes

* The backend needs Python 3.13 (`requires-python = ">=3.13,<3.14"`; the lock files are resolved for
  3.13). If `python --version` shows another version, create the environment with the Python launcher:
  `py -3.13 -m venv .venv`. `py -0p` lists the installed versions; `winget install -e --id
  Python.Python.3.13` installs 3.13 next to them.
* Docker Desktop does not pass file-change events into containers. If hot reload does not pick up
  edits, set `WATCHFILES_FORCE_POLLING=true` and `VITE_USE_POLLING=true` in `.env`.
* The repository forces LF line endings (`.gitattributes`). If the database init script fails with
  `$'\r': command not found`, the file was saved with CRLF; convert it back to LF.

## Configuration

All backend settings are environment variables with the `GIS_` prefix (see `backend/app/core/config.py`).

| Variable | Default | Purpose |
|---|---|---|
| `GIS_ENV` | `development` | `development`, `test` or `production` (production enables the guards below) |
| `GIS_LOG_LEVEL` / `GIS_LOG_FORMAT` | `INFO` / `json` | Log level; `json` or `console` output |
| `GIS_DB_HOST`, `GIS_DB_PORT`, `GIS_DB_NAME` | `localhost`, `5432`, `gis` | Database location |
| `GIS_DB_APP_USER` / `GIS_DB_APP_PASSWORD` | `gis_app` / required for the API | Runtime login |
| `GIS_DB_MIGRATOR_USER` / `GIS_DB_MIGRATOR_PASSWORD` | `gis_migrator` / required for migrations | Migration login |
| `GIS_DB_SSL_MODE` | `disable` | `disable`, `require`, `verify-ca` or `verify-full` |
| `GIS_DB_POOL_SIZE`, `GIS_DB_MAX_OVERFLOW` | `5`, `5` | Connection pool |
| `GIS_DB_STATEMENT_TIMEOUT_MS` | `15000` | Per-statement timeout for API queries |
| `GIS_CORS_ALLOW_ORIGINS` | none | Comma-separated browser origins |
| `GIS_SERVICE_AREA_BBOX` | `79.44,5.66,82.15,10.08` | Accepted positions (WGS84 min lon, min lat, max lon, max lat) |
| `GIS_POSTGIS_MIN_VERSION` | `3.6` | Readiness fails below this PostGIS version |
| `GIS_READINESS_TIMEOUT_S` | `3` | Upper bound for the readiness probe |
| `GIS_DOCS_ENABLED`, `GIS_METRICS_ENABLED` | `true` | Serve `/docs` and `/openapi.json`; serve `/metrics` |
| `GIS_API_ROOT_PATH` | empty | Path prefix when served behind a reverse proxy |
| `GIS_ALEMBIC_CONFIG_PATH` | `db/alembic.ini` | Used by readiness to find the expected migration head |
| `GIS_MAX_REQUEST_BODY_BYTES` | `1048576` | Larger request bodies are refused (413) |
| `GIS_TENANT_ID`, `GIS_TENANT_NAME` | `dialog-smart-alerts`, `Dialog Smart Alerts` | The platform's organisation: requests without `X-GIS-Tenant-Id` act for it; `migrate` registers it |
| `GIS_EXPORT_MAX_FEATURES` | `10000` | Largest export; a larger selection is refused, not truncated |
| `GIS_ENRICHMENT_SETTLEMENT_RADIUS_M`, `..._ROAD_RADIUS_M`, `..._DEVICE_RADIUS_M` | `25000`, `10000`, `5000` | Search radii of the geo-context (inclusive, metres) |
| `GIS_ENRICHMENT_DEVICE_LIMIT` | `5` | Nearby devices in the geo-context (0 turns the lookup off) |

Production guards (`GIS_ENV=production`): wildcard CORS is rejected; `GIS_DB_SSL_MODE` must not be
`disable` unless `GIS_DB_ALLOW_INSECURE_TRANSPORT=true`; the runtime and migration logins must differ.
The GIS has no authentication of its own: route it on the platform's internal network only.

Frontend (Vite, read at dev-server start or build time):

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | API base URL; the dev server proxies `/api` to `GIS_API_PROXY_TARGET` |
| `VITE_BASEMAP_STYLE_URL` | none (`.env.example`: `/basemap/ref-2026.09-dev/style.json`) | MapLibre style for the basemap (`pmtiles://` sources supported) |
| `VITE_BASEMAPS` | none | Several basemaps to switch between, as JSON `[{"id","label","styleUrl"}]` |
| `VITE_TENANT_ID` | none | Tenant whose devices, sites, geofences and events the map reads (sent as `X-GIS-Tenant-Id`; empty: `GIS_TENANT_ID`) |
| `VITE_FEATURE_LIMIT` | `500` | Features per page when reading a layer |
| `VITE_MAX_FEATURE_PAGES` | `4` | Pages to follow per layer per viewport |
| `VITE_EVENT_WINDOW_HOURS` | `24` | Event window the map starts with (at most 31 days) |
| `VITE_EVENT_REFRESH_INTERVAL_MS` | `0` | Re-read events on this interval; `0` on request only |
| `VITE_HEALTH_POLL_INTERVAL_MS` | `15000` | Status panel refresh interval |
| `GIS_BASEMAP_DIR` | `../data/basemap` | Dev and preview servers only: directory served at `/basemap` (Compose mounts it) |

Reference data pipeline (`python -m app.pipeline`): the `GIS_DB_*` settings of the migration login for
loading and publishing, and whatever download variables a profile names (`download_env`,
`auth_header_env`, e.g. `GIS_PIPELINE_OSM_URL` in `production.example.toml`); see
[docs/reference-data/pipeline.md](docs/reference-data/pipeline.md).

The map client is documented in [docs/frontend/map-client.md](docs/frontend/map-client.md): what it
shows, how to embed it in a larger application, and how it measures distances the way the API does.

## Database and migrations

* Logins: `gis_migrator` owns the schemas and runs migrations; `gis_app` is the least-privilege runtime
  login. Both are created by `db/init/20-gis-roles-and-databases.sh` the first time the PostGIS
  container starts, together with the `gis` and `gis_test` databases.
* Migrations run automatically (`migrate` service). To run them yourself:

  ```bash
  docker compose run --rm migrate                                   # upgrade to head
  docker compose run --rm migrate alembic -c /srv/db/alembic.ini current
  docker compose run --rm migrate alembic -c /srv/db/alembic.ini upgrade head --sql   # SQL for review
  ```

* The data model is documented in [docs/database](docs/database/README.md): design rules, a generated
  schema reference ([SCHEMA.md](docs/database/SCHEMA.md)) and an ERD ([ERD.md](docs/database/ERD.md)).
  Regenerate both after changing a migration: `python ../db/tools/generate_schema_docs.py` (from
  `backend/`, against a database at head; `--check` fails when they are out of date).
* Downgrades refuse to drop tables that still hold rows. Empty them deliberately first.
* Row-level security can use spatial indexes only if PostGIS's `&&` operator is LEAKPROOF. The init
  script sets this; for databases created otherwise, and after every `ALTER EXTENSION postgis UPDATE`,
  run `psql -U postgres -d gis -f db/admin/postgis-leakproof.sql` as a superuser. Readiness warns
  (`tenant_spatial_indexes`) while it is missing.
* To create a new revision, work from a local Python environment (next section) so the new file lands
  in `db/migrations/versions`:

  ```bash
  cd backend
  alembic -c ../db/alembic.ini revision -m "add reference admin boundaries"
  ```

  Revision IDs follow `YYYYMMDD_NNNN`; pass `--rev-id 20261001_0006` to set one. Hand-written DDL
  should use the helpers in `db/migrations/migration_support.py`, and the ORM models must be updated to
  match (the parity test checks this).

### Reference data

Reference data is loaded into versioned, immutable releases (`ref-YYYY.MM[-suffix]`) by the migration
login. The pipeline ([docs/reference-data/pipeline.md](docs/reference-data/pipeline.md)) builds a release
from the sources a profile names (GDAL/ogr2ogr, GeoPandas, Shapely, pyproj), records the source, licence,
reference, version, CRS and operation, accuracy and checksums of every dataset, checks it (file QA, then
database QA with `ST_IsValid`, duplicates, identifiers, outliers, extents and topology) and publishes it
only when the checks pass:

```bash
# The committed development release (no GDAL needed)
docker compose --profile sample run --rm sample-data

# Build a release from sources (GDAL; the pipeline service mounts data/)
docker compose --profile pipeline run --rm pipeline run --profile /srv/data/pipeline/profiles/dev.toml --basemap --current

# Local environment (from backend/; pip install -e '.[pipeline]' and gdal-bin for building)
python -m app.pipeline load ../data/sample/ref-2026.09-dev --basemap ../data/basemap/ref-2026.09-dev --current
python -m app.pipeline status ref-2026.09-dev
```

Licences are never assumed: a production profile needs an approved licence review for every source,
WDPA and other restricted licences need written permission, and data that may not be redistributed is
not exported. The test fixtures ([data/fixtures](data/fixtures/README.md)) load with
`python -m app.tools.load_reference_data <manifest> --current`. Published releases are listed at
`GET /geo/v1/releases` ([docs/api/releases.md](docs/api/releases.md)).

## Local development without containers (optional)

Run only the database in Docker, and the API and web client on the host.

```bash
docker compose up -d db

# Backend (Python 3.13)
cd backend
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements-dev.lock && pip install --no-deps -e .
export GIS_DB_HOST=localhost GIS_DB_PORT=5434 GIS_DB_APP_PASSWORD=... GIS_DB_MIGRATOR_PASSWORD=...
alembic -c ../db/alembic.ini upgrade head
uvicorn app.main:create_app --factory --reload --port 8100

# Frontend (Node 24)
cd frontend
npm ci
GIS_API_PROXY_TARGET=http://localhost:8100 npm run dev -- --port 5174   # proxies /api to the API
```

### Opening the map on real data

The map reads the same API as everything else, without credentials. By default it shows the platform's
organisation (`GIS_TENANT_ID`); to look at another tenant, such as the demonstration tenant, name it in
`frontend/.env.local` (git-ignored):

```dotenv
# frontend/.env.local
VITE_TENANT_ID=wildlife-dept
VITE_BASEMAP_STYLE_URL=/basemap/ref-2026.09-dev/style.json   # empty: a neutral background
```

The dev server serves the pipeline's basemaps (`data/basemap`) at `/basemap`. Reference data must be
loaded for the reference layers to have anything to show (see above). How the main platform shows the
map is in [docs/integration.md](docs/integration.md) and [docs/frontend/map-client.md](docs/frontend/map-client.md).

## Tests and quality checks

### Backend

```bash
# In Docker, against the gis_test database (fails if the database is unavailable):
docker compose --profile test run --rm --build backend-tests

# Locally:
cd backend
pytest tests/unit                          # no database needed
pytest tests/pipeline                      # the pipeline extra and gdal-bin; skipped without them
GIS_DB_NAME=gis_test pytest                # unit + pipeline + integration (GIS_DB_* must point at PostGIS)
ruff check . ../db ../data && ruff format --check . ../db ../data
mypy app ../db/migrations ../db/tools tests
python ../db/tools/generate_schema_docs.py --check   # schema docs match the migrations
```

Integration tests migrate the target database down and up again, so they refuse to run unless
`GIS_DB_NAME` ends in `_test`. Without database settings they are skipped; `GIS_REQUIRE_DB=1` turns that
into a failure. The suites cover:

* configuration validation and production guards
* HTTP behaviour: problem details, request IDs, metrics, CORS
* readiness against a live and a broken database
* migrations: upgrade, downgrade, least-privilege grants, refusal to drop non-empty schemas and tables,
  offline SQL, ORM/migration parity
* transaction-scoped tenant context on pooled connections; row-level security and sharing policies
* spatial regression: the SLD99 grid origin, database/application transform agreement, distance accuracy
  and the inclusive 500 m threshold
* the data model: point inside, outside and on the boundary of polygons (and enclaves); distances exactly
  at a threshold; invalid polygons (repaired for reference data, rejected for tenants and events);
  swapped latitude/longitude; Sri Lankan and foreign coordinates; EPSG:4326 <-> EPSG:5235; field-of-view
  sectors; circle and corridor geofences; releases, lineage and licences; event partitions; spatial and
  temporal indexes; the absence of any alerting tables
* geo-context enrichment: a normal event, protected areas, geofences, settlements and roads, several and
  no zones, boundary points, 499 / 500 / 501 m around a 500 m threshold, invalid coordinates, tenant
  isolation, missing reference data, determinism, the number of statements per event, index use on
  20 000-row tables and a brute-force comparison
* `POST /geo/v1/enrich` over HTTP: no credentials, the tenant a request acts for (`X-GIS-Tenant-Id`, else
  `GIS_TENANT_ID`), problem details, request size limit, the OpenAPI document and its
  example, which must equal a real result
* the spatial query API: the layer catalogue against the registry, viewport, attribute and validity
  filters, cursor paging (every row once, cursors refused for another query), within-distance and nearest
  compared row by row with the database's own arithmetic, containment including enclaves, boundaries and
  the exact circle of a geofence, reverse geocoding, event queries by window, viewport, type, geofence and
  administrative area, and `EXPLAIN` checks that the statements still use the spatial indexes
* geofences, sites and device placements over HTTP: the three shapes stored as defined, versions and
  409 conflicts, sharing policies, archive and purge, and a geofence created through the API producing
  the expected geo-context hit
* tenant isolation from both sides: another tenant's private objects are absent from features, queries,
  containment, events, reads and writes, and a shared object can be read but not changed
* migration 0006 converting stored geo-context documents in both directions
* the reference data pipeline: licence refusals (WDPA, non-commercial, unreviewed production sources,
  placeholders), CRS resolution without guessing, the operation's accuracy, ogr2ogr and pyproj agreeing
  and control points, OSM tag rules, file QA, byte-identical rebuilds, an SLD99 source built end to end,
  the OSM PBF header, provenance records; database QA findings, the publish gate (unchecked, stale,
  unwaived errors), waivers and their audit, the production environment rule, lineage of every dataset,
  the releases API, attribution and refused exports, and the development seed
* the MVP scenario end to end over HTTP (`test_end_to_end.py`): an event submitted, validated (swapped
  axes and invalid polygons refused), enriched with administrative areas, nearest settlement and road,
  overlapping zones and geofence hits, stored and returned, found by viewport, geofence and area queries,
  and a geofence created, replaced with a version and archived
* the service boundary in code: no identifier, file or dependency about alerts, notifications,
  recipients or messaging (`test_service_boundary.py`, [docs/boundary-audit.md](docs/boundary-audit.md))

The integration tests load the fixtures into a freshly migrated `gis_test` database for each test module
(about 2 seconds). The whole backend suite (1 199 tests) takes about two minutes. Which test covers which
requirement and boundary case (499/500/501 m, boundaries, invalid polygons, swapped coordinates, empty
results, overlapping zones) is listed in [docs/testing.md](docs/testing.md).

### Frontend

```bash
cd frontend
npm run typecheck
npm run lint
npm test               # 315 tests, jsdom; no database and no browser needed
npm run build
npm run e2e            # browser end-to-end tests against a running API (docs/testing.md)
```

The map library needs WebGL, which jsdom does not have, so it is mocked and the components' own
behaviour is what is tested. The suite covers:

* the EPSG:5235 transformation against values exported from PROJ itself, forwards and back
  (`python -m app.tools.export_crs_reference` regenerates the fixture after a PROJ upgrade)
* geometry: bounds, containment with the boundary counted as inside, ring validity and self-intersection,
  areas, the exact circle of a radius, and recovering the centre and radius of a drawn ring
* the API boundary against a recorded `fetch`: the tenant header and no credentials, query strings, problem details with their
  codes and extensions, schema mismatches, and the request each endpoint function builds
* layer loading: what is requested for a viewport, what is refused by zoom or by the service area, cursor
  paging, keeping the previous features while the next window loads, and failures
* events: the resolved window, the window the service answered for, and the filters that were sent
* the spatial tools: the queries they send, the ruler, results and refusals
* the geofence editor: a drawn circle becoming a centre and a radius, a polygon staying editable, every
  validation rule, what is sent on create and replace, version conflicts, archive and purge
* the components: layer visibility and groups, the legend, event filters, the status line, the popup with
  its geographic context, selection through a map click, and the container mounting a source per layer
* reference data licences: the catalogue's attribution is shown on the map, a layer whose licence
  forbids redistribution is not offered for export, an export shows the attribution to keep with it, and
  every style layer of a reference layer is drawn from its source
* the service boundary: the client's own source is read and must contain no notification, recipient or
  channel vocabulary, and every path it calls must be one of the service's geographic endpoints
* drawing: the click that finishes a shape selects nothing, and a drawn circle keeps its shape after
  Terra Draw's ring is removed; only changes to the shape the editor holds count (not the handles Terra
  Draw adds and removes, nor an unfinished drawing); a geofence opened for editing keeps its geometry
  when effects run twice; Terra Draw starts again on a new basemap style; a view opened from a link
  (`#map=<zoom>/<lat>/<lon>`) is kept

In a real browser (`npm run e2e`, Playwright and Chromium), an event submitted to the API appears on the
map with its geographic context, a circle drawn with the editor is stored and hit by an event, and after
a basemap switch a polygon is drawn, edited, deselected and stored as edited
([docs/testing.md](docs/testing.md#browser-end-to-end-tests)).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `db` never becomes healthy; logs show `gis-init: ... placeholder value` | A `CHANGE_ME` value is still in `.env`. Set real passwords, then `docker compose down -v` (the first start was incomplete) and start again |
| Changed passwords in `.env` have no effect | Logins are created only when the volume is first initialised. Change them in PostgreSQL, or reset with `docker compose down -v` (deletes local data) |
| `/health/ready` returns 503 with `migrations` failing | Run `docker compose run --rm migrate`, or check that the API image and the database are on the same revision |
| `crs_consistency` shows a warning | The database and application PROJ versions transform differently; check the reported offset and the PROJ versions in the readiness details |
| `downgrade refused: <table> contains rows` | Downgrades never discard data. Export what you need, empty the tables (for a disposable database: `docker compose down -v`), then downgrade |
| `no partition of relation "event_location" found for row`, or "too old to be stored without preparation" | The month of `observedAt` has no partition. The service creates recent months itself; for older months (historical imports) run, as the migration login, `SELECT geo.prepare_event_partitions('2024-01-01', '2024-12-31')` |
| `... reference data release ... is published` | Published releases are immutable. Load corrections into a new release (`--release ref-YYYY.MM-fix1`) |
| 403 `tenant_not_registered` | The tenant the request acts for is not registered: `docker compose run --rm migrate` registers `GIS_TENANT_ID`; others with `python -m app.tools.register_tenant --tenant <id> --name <name>` |
| 403 `forbidden` naming `tenantId` | `tenantId` in the request is not the tenant it acts for (`X-GIS-Tenant-Id`, else `GIS_TENANT_ID`) |
| 503 `reference_data_unavailable` | No release is current: load one with `--current` |
| Readiness warns `tenant_spatial_indexes` | Run `db/admin/postgis-leakproof.sql` as a superuser (see "Database and migrations") |
| Port already in use | Change `GIS_DB_HOST_PORT`, `GIS_API_HOST_PORT` or `GIS_WEB_HOST_PORT` in `.env` |
| Map area shows a WebGL2 message | MapLibre GL JS v6 needs WebGL2; enable hardware acceleration or use a current browser |
| Map is plain grey | No basemap: build or copy `data/basemap/ref-2026.09-dev` and set `VITE_BASEMAP_STYLE_URL=/basemap/ref-2026.09-dev/style.json` (a 404 on `/basemap/...` means the directory is not there) |
| Reference layers are empty | No current release: `docker compose --profile sample run --rm sample-data` |
| `LicenceError` from the pipeline | A source's licence is unreviewed (production), restricted or rejected: record the review or permission in the profile |
| `unresolved QA errors` when publishing | Fix the data, or waive acceptable findings with a reason (`python -m app.pipeline waive`) |
| Map shows no operational data | The map shows `VITE_TENANT_ID`, else `GIS_TENANT_ID`: that tenant has no devices, sites, geofences or events yet (the platform syncs its devices; `-WithSampleTenant` plus `VITE_TENANT_ID=wildlife-dept` shows the demonstration tenant) |
| A layer stays empty | Check the status line on the map: it says "zoom in", "off area", or names the layer that failed |
| Devices are all grey | No device state provider is wired in; the GIS service does not collect device health (see docs/frontend/map-client.md) |

## Updating dependencies

```bash
# Python: edit backend/pyproject.toml, then regenerate the three locks
cd backend
uv pip compile pyproject.toml --universal --python-version 3.13 --generate-hashes --no-header -o requirements.lock
uv pip compile pyproject.toml --extra dev --universal --python-version 3.13 --generate-hashes --no-header -o requirements-dev.lock
uv pip compile pyproject.toml --extra pipeline --extra dev --universal --python-version 3.13 --generate-hashes --no-header -c requirements-dev.lock -o requirements-pipeline.lock

# Frontend: exact versions are pinned in package.json
cd frontend
npm install <package>@<version> --save-exact
```

Upgrade PostGIS, MapLibre and other spatial dependencies only after the spatial regression suite passes
(plan §4.4).
