# Performance

Measured on 2026-09-25 with `python -m app.tools.benchmark` (reports in [`performance/`](performance/)).
These are single-client, sequential measurements on a development machine: they show where time goes and
that every query uses its indexes. They are not a capacity test (see *Not measured* below).

## Setup

| | |
|---|---|
| Machine | Linux container, 2 vCPU, PostgreSQL 18.6 + PostGIS 3.6.4 and the API on the same host |
| Reference data | Release `ref-2026.09-dev` (the development sample): 29 155 roads, 5 482 subdivided area parts (913 admin areas, protected areas, risk zones), 4 917 water bodies, 1 602 facilities, 605 settlements |
| Tenant data | `wildlife-dept` (the sample tenant): 5 sites, 6 devices, 3 geofences, about 1 400 events in the last 24 hours |
| Positions | 300 events on a low-discrepancy sequence over the pilot area plus 75 over the whole country; 100 query positions per operation over the pilot area; 10 warm-up requests not counted |
| Database setting | `&&` marked LEAKPROOF (`db/admin/postgis-leakproof.sql`), as the container initialisation does |

## Results

Latency per request in milliseconds. *In-process*: the application built by `create_app`, called through
its full HTTP stack (authentication, validation, services, PostGIS, row-level security, audit log) without a
network. *HTTP*: the same requests to the API served by uvicorn on the same host.

| Operation | In-process p50 | p95 | p99 | HTTP p50 | p95 | p99 |
|---|---|---|---|---|---|---|
| `POST /geo/v1/enrich` (store event, compute and store geo-context) | 8.2 | 10.2 | 13.4 | 9.7 | 12.6 | 15.1 |
| `GET /geo/v1/layers/ref.road/features`, 2 km viewport | 4.8 | 6.2 | 6.5 | 6.0 | 7.2 | 7.7 |
| `GET /geo/v1/layers/ref.admin_area/features`, 2 km viewport, GN level | 4.2 | 5.2 | 6.8 | 5.4 | 6.3 | 7.5 |
| `GET /geo/v1/layers/ops.geofence/features`, 2 km viewport | 5.2 | 6.0 | 6.8 | 6.2 | 7.4 | 8.3 |
| `POST /geo/v1/query/within-distance`, facilities within 5 km | 5.8 | 8.4 | 22.5 | 6.2 | 7.3 | 8.1 |
| `POST /geo/v1/query/nearest`, 5 settlements | 5.4 | 6.4 | 7.0 | 6.3 | 7.0 | 7.2 |
| `POST /geo/v1/query/contains`, admin areas at a point | 10.0 | 11.3 | 11.9 | 10.7 | 11.7 | 12.6 |
| `GET /geo/v1/reverse` | 5.9 | 7.1 | 7.9 | 6.7 | 8.3 | 9.7 |
| `GET /geo/v1/events`, 10 km viewport, 24 hours | 6.5 | 8.3 | 10.4 | 7.6 | 9.2 | 9.8 |

No request failed. `contains` on administrative areas is the slowest because it returns the full polygon
of each containing area (province, district, DS and GN division) as GeoJSON; the lookup itself takes
3.5 ms.

### At 200 000 events a day

To see whether the event queries hold up at volume, 200 000 synthetic events of the tenant were inserted
into the last 20 hours (spread over the country) and the benchmark repeated
([report](performance/2026-09-25-200k-events.json)):

| Operation | p50 | p95 | Plan |
|---|---|---|---|
| `GET /geo/v1/events`, 10 km viewport, 24 hours | 11.6 | 14.4 | Bitmap scan of the partition's GiST index on `geom`, 10.5 ms execution |
| Same, **without** the LEAKPROOF setting | 44.4 | 58.2 | Walks the `(tenant_id, observed_at)` index and filters by area: 200 784 buffers, 75 ms execution |
| `POST /geo/v1/enrich` | 8.3 | 10.2 | Unchanged: enrichment reads no events |

The LEAKPROOF setting is what lets row-level security use spatial indexes on tenant tables; without it,
correctness is the same but tenant-table lookups degrade with volume. The readiness check reports it
(`tenant_spatial_indexes`).

## Query plans

The benchmark captures the statements each operation executes and replays them with
`EXPLAIN (ANALYZE, BUFFERS)` in the same tenant context. Every access to a table of any size is an index
scan:

| Operation | Execution | Index used on the large tables |
|---|---|---|
| Enrichment lookup (one statement for the whole geo-context) | 2.1 ms | `area_part` GiST (admin areas, protected areas, risk zones), `road` and `settlement` GiST in EPSG:5235 with KNN ordering bounded by the search radius, `geofence` GiST (tenant + geometry and metric), `device` GiST |
| Features, viewport | 0.4-1.0 ms | `road`, `admin_area` GiST on `(release_id, geom)`; `geofence` GiST on `(tenant_id, geom)` |
| Within-distance, nearest | 0.4-0.5 ms | `facility`, `settlement` GiST on `(release_id, geom_metric)` |
| Contains | 3.5 ms | `area_part` GiST, then `admin_area` by key |
| Reverse geocoding | 1.2 ms | `area_part`, `road`, `settlement` GiST |
| Events | 0.6 ms (10.5 ms at 200 000/day) | the month's partition only; its GiST index on `geom` |

Sequential scans appear only on tables of a handful of rows (`ref_data_release`, the sample tenant's
`device` table, empty event partitions of other months), where the planner rightly prefers them. The
same statements are held to index use on bulk data by the test suite
(`test_enrichment_indexes.py`: 20 000 settlements, 10 000 roads, 2 000 risk zones, 20 000 devices,
10 000 geofences; `test_spatial_query_regression.py`).

**Planning time.** A replayed statement on a fresh connection spends 6-24 ms in planning (the
enrichment statement is the largest), more than it spends executing. The service does not pay this per
request: the connection pool keeps connections, and asyncpg prepares and caches statements per
connection, which is why the served p50 latencies above are below the cold planning times. Keep the pool
warm (`GIS_DB_POOL_SIZE`) rather than recycling connections aggressively.

## Indexes

No index was added. Every query in the table above already uses a spatial or key index, and the one
slow case found (events at 200 000 a day) is solved by the LEAKPROOF setting the deployment already
applies, not by another index. Candidates considered and not added:

* a composite GiST `(tenant_id, geom)` on event partitions: the per-partition GiST on `geom` plus the
  tenant filter already gives 10 ms at 200 000 events a day;
* indexes on `geo.event_geo_context` for administrative levels other than 2: event queries by
  administrative area are bounded to a time window and one tenant, and were not slow in any
  measurement; add one when a measurement shows the need.

## Reproducing

```bash
cd backend
# GIS_DB_* for the runtime login, as for the API
python -m app.tools.benchmark --output benchmark.json
python -m app.tools.benchmark --api-url http://localhost:8100 --no-explain
```

Options: `--tenant` (default `wildlife-dept`), `--events`, `--queries`, `--warmup`. The benchmark stores
its events (type `benchmark.synthetic`) in the tenant, so run it against a development database. It
refuses `GIS_ENV=production`, and refuses any service (in process or over HTTP) whose current reference
data release is not a development or test release. Table row counts are reported only for the in-process
run, where the local database is the one measured.

## Not measured

* Concurrent load and throughput (requests per second at a given latency), connection-pool saturation,
  and behaviour under a production-sized event stream over weeks.
* Network latency between clients, the API and a managed database.
* The map client's rendering performance on field devices.
