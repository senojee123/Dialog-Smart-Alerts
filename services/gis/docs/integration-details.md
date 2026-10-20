# The GIS instance in Dialog Smart Alerts: full details

> Start with the short guide, [integration.md](integration.md). This page is for the engineers who run,
> deploy and change the integration.

The GIS Core Service lives in the platform's repository as `services/gis`. It runs as its own service with
its own PostgreSQL + PostGIS database. The platform's FastAPI backend is the only thing that talks to it.

---

## 1. The pieces

| Where | What | Changed for the integration |
|---|---|---|
| `services/gis/` | The GIS service: API, map, reference data pipeline, database migrations, tests | No login of its own ([ADR-0019](adr/ADR-0019-platform-instance-without-own-authentication.md)); serves its built map at `/app` and basemaps at `/basemap`; tells the embedding page what was clicked |
| `backend/gis_client.py` | The platform's connector: proxy, enrichment, device sync, health | New |
| `backend/server.py` | Calls the connector | About 30 lines: enrichment in `_ingest_event`, device sync on create/update/delete and at start-up, `gis_ok` in `/api/system/health`, the `gis` summary on incidents, the proxy routes |
| `src/pages/GIS.jsx` | The dashboard's GIS page | Was empty; now shows the GIS map |
| `src/pages/MapView.jsx`, `src/components/map/MapPanel.jsx`, `App.jsx`, `NavSidebar.jsx` | The old Map View page | Removed: the GIS page shows the same and more; `/map` redirects to `/gis` |
| `src/components/incidents/IncidentDetail.jsx` | Incident panel | New **Location (GIS)** section and **Show on GIS map** link |
| `vite.config.js` | Dev server proxy | `/gis-app` and `/basemap` to the backend |
| `requirements.txt`, `backend/requirements.txt` | Python packages | `httpx` |

The rule engine, notifier, spatial sign engine, MQTT client, simulator and all other pages are unchanged.

## 2. Local development

You need Docker Desktop (for GIS), and Python and Node as before (for the platform).

```powershell
# 1. The GIS service (first time: builds images and loads the development map data, several minutes)
cd services\gis
.\setup.ps1                      # database :5434, API :8100, GIS dev map :5174

# 2. The platform, as before
cd ..\..\backend
pip install -r requirements.txt  # adds httpx
python server.py                 # :8000; GIS_API_URL defaults to http://localhost:8100

# 3. The dashboard
cd ..
npm install
npm run dev                      # :5173 -> GIS page
```

- **Order doesn't matter.** If the platform starts first, it places the devices once GIS answers
  (start-up sync retries for about 2.5 minutes). Devices saved later are placed when saved.
- **Stop GIS:** `docker compose down` in `services/gis`. Its data stays in a Docker volume; `down -v`
  deletes it.
- **Without GIS:** set `GIS_ENABLED=false` for the platform. Detections, incidents and the dashboard work
  as before; the GIS page and the Location (GIS) section stay empty.

**Careful when testing locally.** The platform's notifier sends real SMS through Ideabiz using
credentials written into `backend/notifier.py`. The MQTT client connects to the public HiveMQ broker,
where the real modem gateway publishes. To test without either:

```bash
IDEABIZ_API_URL=http://127.0.0.1:1/disabled MQTT_BROKER_HOST=127.0.0.1 MQTT_BROKER_PORT=1 python server.py
```

## 3. Settings

Platform (environment variables, read by `gis_client.py`):

| Variable | Default | Meaning |
|---|---|---|
| `GIS_ENABLED` | `true` | `false` switches every GIS call off |
| `GIS_API_URL` | `http://localhost:8100` | Where the GIS service is (Railway: its private address) |
| `GIS_TENANT_ID` | `dialog-smart-alerts` | The organisation the platform acts for in GIS (sent as `X-GIS-Tenant-Id`) |
| `GIS_ENRICH_TIMEOUT_S` | `2` | How long a detection waits for its GIS details before going on without them |

GIS service (environment variables, full list in the [README](../README.md#configuration)):

| Variable | Value for the platform |
|---|---|
| `GIS_DB_HOST`, `GIS_DB_PORT`, `GIS_DB_NAME`, `GIS_DB_APP_USER`, `GIS_DB_APP_PASSWORD` | The GIS database and its runtime login |
| `GIS_DB_MIGRATOR_USER`, `GIS_DB_MIGRATOR_PASSWORD` | Its migration login (migrations, registering the tenant, loading map data) |
| `GIS_TENANT_ID` | `dialog-smart-alerts` (the same as the platform's) |
| `GIS_ENV` | `production` on Railway: then also `GIS_DB_SSL_MODE=require`, or `GIS_DB_ALLOW_INSECURE_TRANSPORT=true` on the private network |
| `GIS_DOCS_ENABLED` | `false` in production |
| `GIS_RUN_MIGRATIONS`, `GIS_LOAD_SAMPLE_REFERENCE` | `true` to migrate, register the tenant and load the development map data at start-up (`docker/platform-start.sh`) |

## 4. What travels between them

### Detections → GIS (`POST /geo/v1/enrich`)

| GIS member | From the platform's detection |
|---|---|
| `eventId` | the detection id (`EVT-…`) |
| `tenantId` | `GIS_TENANT_ID` |
| `observedAt` | `captured_at` when it has a time zone, else `received_at` |
| `eventType` | `detection.<object_type>` (e.g. `detection.elephant`) |
| `sourceType` | `device` → `sensor`, `ingestion`/`simulation` → `external`, `upload` → `manual` |
| `sourceRef` | the platform device id (never `external_id`, which falls back to the device's API key) |
| `location` | `[lng, lat]` of the detection (GeoJSON order) |
| `deviceId` | the device's GIS id (see below). If GIS doesn't know the device yet, it is placed and the detection is enriched by position |
| `metadata` | source, object type, confidence, use case, zone |

The answer is stored on the detection as `geo_context`. Incidents get a `gis` summary from their latest
detection with one, which the incident panel shows:

- `district`, `province`, `ds_division`, `gn_division`;
- `nearest_settlement`, `settlement_distance_m`, `nearest_road`, `road_class`, `road_distance_m`;
- `inside_zones`, `geofence_hits`, `nearby_devices`, `ref_data_release`, `event_id`.

`distance_to_road_m`, which the incident already had and nothing used to fill, now comes from GIS.

Rules and SMS templates do **not** use the GIS details yet. Rules like "inside Yala National Park" or
templates with `{district}` are a possible next step; they change alerting, so they need a decision.

### Devices → GIS (`PUT /geo/v1/devices/{id}/placement`)

- **The device's GIS id:** a fixed UUID derived from its platform id, so no mapping is stored.
- **Types:**

  | Platform type | GIS type |
  |---|---|
  | `camera`, `thermal` | `camera` |
  | `acoustic` | `acoustic_sensor` |
  | `pressure_pad` | `seismic_sensor` |
  | `siren`, `gate` | `other` |

  `manual` (phones) and `drone` move around, so they aren't placed.
- **Status:** a `disabled` device becomes `inactive` in GIS, and a deleted one `decommissioned`.
- **Road sign boards** aren't placed; they stay on the platform's Road Signs page.

### The GIS page

The page shows `/gis-app/` in a frame (same origin); the map leaves out its own header there. Clicking a
detection shows its details in the map's own popup - nothing is passed to the platform's page. The page
opens the map at `?lat=&lng=` (as `#map=16/lat/lng`), which is where **Show on GIS map** on an incident
links.

## 5. Railway

GIS is a second service in the same Railway project, plus a database:

1. **Database.** Add a service from the Docker image `postgis/postgis:18-3.6` with a volume on
   `/var/lib/postgresql`. Set `POSTGRES_PASSWORD`, then create the two GIS logins and the `gis` database
   once, with the SQL in [section 7](#7-a-database-you-create-yourself).
2. **GIS service.**
   - Source: the same GitHub repository, root directory `services/gis`, Dockerfile
     `docker/backend.Dockerfile` (its default target, `platform`).
   - Variables: those in section 3, with `GIS_RUN_MIGRATIONS=true` and, for the development map data,
     `GIS_LOAD_SAMPLE_REFERENCE=true`.
   - **Don't generate a public domain:** the service has no login.
3. **Platform service.** Add `GIS_API_URL=http://<gis-service>.railway.internal:<its PORT>`.

The platform image carries the built map, the offline basemap (`data/basemap/ref-2026.09-dev`, 22 MB,
committed for this) and the development map data. Tencent Cloud works the same way:
- run the GIS image as a container, with TencentDB for PostgreSQL if its PostGIS is 3.6 or newer (check),
  or the `postgis/postgis:18-3.6` image;
- keep the GIS container private.

## 6. Map data

- **Development release:** `ref-2026.09-dev`.
  - All of Sri Lanka: districts, divisions, national roads, towns, protected areas, water, placeholder
    risk zones.
  - Villages and local roads only around Habarana (the pilot area).
  - The B43/Yala area gets district, division, Yala National Park, the nearest named road and the nearest
    town.
- **To add detail elsewhere:** extend the pilot area in a pipeline profile
  ([reference-data/pipeline.md](reference-data/pipeline.md)).
- **For production:** official datasets with licence reviews (Survey Department, DWC, RDA, …), built as a
  *production* release.

## 7. A database you create yourself

On a managed PostgreSQL 18 with PostGIS 3.6, an administrator runs once:

```sql
CREATE ROLE gis_migrator LOGIN PASSWORD '<migrator password>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE gis_app LOGIN PASSWORD '<runtime password>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
CREATE DATABASE gis OWNER gis_migrator TEMPLATE template0 ENCODING 'UTF8';
REVOKE ALL ON DATABASE gis FROM PUBLIC;
GRANT CONNECT ON DATABASE gis TO gis_app;
\connect gis
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CREATE ON SCHEMA public TO gis_migrator;
ALTER FUNCTION public.geometry_overlaps(public.geometry, public.geometry) LEAKPROOF;  -- needs a superuser
```

The migrations create everything else. The `postgis/postgis` container does all of this itself on first
start (`db/init/20-gis-roles-and-databases.sh`).

## 8. Tests

| What | Command | Result on 14 Oct 2026 |
|---|---|---|
| GIS backend | `cd services/gis/backend && pytest` (needs the GIS database, `GIS_DB_NAME=gis_test`) | 1 068 passed; 3 fail on this Windows machine and fail identically in v1: two because the Windows clock is 15 s behind Docker's, one because a test's fixed date window is now over 31 days old |
| GIS frontend | `cd services/gis/frontend && npm test` | 323 passed |
| GIS browser | `npm run e2e` (needs the GIS stack) | 1 of 3; the two geofence scenarios hit the same clock difference |
| Platform + GIS | manual, in a browser | device sync, enrichment, the incident's Location (GIS), the GIS page, event markers and their click targets, POST and GET through the proxy, basemap range requests |

## 9. Troubleshooting

| Symptom | Cause |
|---|---|
| GIS page blank, or `/gis-app/` answers 502 | GIS not running or `GIS_API_URL` wrong; `curl $GIS_API_URL/health/ready` |
| Incidents have no Location (GIS) | GIS was down or slower than `GIS_ENRICH_TIMEOUT_S` when the detection arrived (the platform log says `[GIS] enrich … skipped`), or the detection had no position |
| `[GIS] enrich … HTTP 403 tenant_not_registered` | GIS hasn't registered `GIS_TENANT_ID`: run its migrations (`docker compose run --rm migrate`) |
| `[GIS] enrich … HTTP 503 reference_data_unavailable` | No map data loaded: `.\setup.ps1`, or `GIS_LOAD_SAMPLE_REFERENCE=true` |
| Devices missing on the GIS map | They have no `lat`/`lng`, are `manual`/`drone`, or GIS was down when they were saved: save them again or restart the platform |
| Grey map without roads | The basemap isn't served: check `/basemap/ref-2026.09-dev/style.json` through the platform |
