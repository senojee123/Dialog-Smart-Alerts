# Test guide

What is tested, where, and how to run it. Counts as of 2026-09-28: **1 199 backend tests** (655 unit,
35 pipeline, 509 integration), **315 frontend tests** (38 files) and **3 browser end-to-end tests**, all
passing.

## Running the tests

| Suite | Command | Needs |
|---|---|---|
| Backend unit | `cd backend && pytest tests/unit` | Python 3.13 and `requirements-dev.lock` |
| Pipeline | `cd backend && pytest tests/pipeline` | the `pipeline` extra and `gdal-bin` (skipped without them; `GIS_REQUIRE_PIPELINE=1` fails instead) |
| Backend integration and API | `cd backend && GIS_DB_NAME=gis_test pytest tests/integration` | PostgreSQL 18 + PostGIS 3.6 with both logins (`GIS_DB_*`); the database name must end in `_test` |
| Everything, in Docker | `docker compose --profile test run --rm --build backend-tests` | Docker; uses the `gis_test` database of the stack |
| Frontend | `cd frontend && npm test` (also `npm run typecheck`, `npm run lint`, `npm run build`) | Node 24 |
| Browser end to end | `cd frontend && npm run e2e` (see below) | a running API with the development sample, Chromium (`npx playwright install chromium`) |
| Quality gates | `cd backend && ruff check . ../db ../data && ruff format --check . ../db ../data && mypy app ../db/migrations ../db/tools tests` and `python ../db/tools/generate_schema_docs.py --check` | - |

Integration tests migrate the target database down to nothing and up again and load the fixtures per
module (about two seconds each); `GIS_REQUIRE_DB=1` turns a missing database into a failure instead of a
skip. The whole backend suite takes about two minutes.

### Browser end-to-end tests

`frontend/e2e/map.e2e.ts` drives the real map client in Chromium against a running API:

1. an event submitted to `POST /geo/v1/enrich` (with an id and event type of the run) appears on the
   MapLibre map, is selected by a click, and its popup shows the geographic context the service resolved
   (province, nearest settlement and road, release);
2. a circle geofence drawn with the editor (two clicks on the map) is stored by the service with the
   drawn centre and radius, and an event inside it records the hit;
3. after a basemap switch (which replaces the map style under Terra Draw), a polygon is drawn, selected,
   a corner dragged and the polygon deselected; the service stores it as edited, and an event inside it
   records the hit.

Every test also asserts that the page raised no uncaught error: some failures, such as Terra Draw
rendering into a source that no longer exists, never reach the DOM. Geofences the tests create are
archived at the end, also when an assertion fails.

```bash
docker compose up -d && docker compose --profile sample run --rm sample-data   # the sample tenant
cd frontend && npx playwright install chromium && npm run e2e
```

The test starts its own dev server on port 5175 (for the tenant `E2E_TENANT`, default `wildlife-dept`,
with the basemap); set `E2E_BASE_URL` to use a running one, `E2E_API_URL` for an API elsewhere than
`http://127.0.0.1:8100`. No credentials are needed. Screenshots of the scenarios are written to
`frontend/test-results/`.

The geofence scenarios compare the time an event was observed (the browser's clock) with the time a
geofence took effect (the database's clock). When the host clock lags the Docker VM by more than a few
seconds (seen on Windows), the event counts as earlier than the geofence and no hit is recorded; sync the
host clock (Windows: Settings -> Time -> Sync now) before running them.

## What is tested

| Category | Where | Examples |
|---|---|---|
| Unit | `backend/tests/unit` | configuration and production guards, access and permissions, the caller and its tenant, GeoJSON and coordinate validation, EPSG:5235 transformation, paging cursors, contracts of the data model and the query API, pipeline profiles and licence rules, the service boundary (identifiers, imports of delivery libraries, dependencies), the benchmark tool and its release guard |
| Integration | `backend/tests/integration` | the data model against PostGIS (constraints, triggers, repairs, partitions), the enrichment engine, the reference loader, releases and QA, the seed |
| API | `test_enrich_api.py`, `test_spatial_query_api.py`, `test_event_query_api.py`, `test_operational_api.py`, `test_audit_log.py`, `test_reference_releases_api.py` | every endpoint over HTTP without credentials: answers, problems and their codes, the tenant a request acts for, audit entries, the OpenAPI document |
| Spatial regression | `test_postgis_regression.py`, `test_spatial_query_regression.py`, `test_geo_context.py`, `frontend/src/geo/sld99.test.ts` | SLD99 grid origin, database and application transforming identically (and the client, against PROJ's own numbers), grid vs geodesic distance, query results against row-by-row scans, paging completeness, index use in plans |
| Database migrations | `test_migrations.py`, `test_model_parity.py` | upgrade, downgrade and round trip, least-privilege grants, refusal to drop data, offline SQL, the document-layout conversion both ways, ORM and schema documentation matching the migrations |
| Geometry validation | `test_geojson_validation.py`, `test_spatial_validation.py`, `test_spatial_model.py`, `frontend/src/geo/geometry.test.ts`, `geofenceDraft.test.ts` | invalid and self-intersecting polygons, empty and degenerate geometries, unclosed rings, `crs` members, positions outside the service area, repairs of reference data and rejection of tenant geometries |
| Tenant isolation | `test_tenant_isolation.py`, `test_tenant_context.py`, `test_privacy.py` | every tenant table carries the tenant and row-level security, the runtime login cannot bypass it, no private row of another tenant is visible or writable, a tenant header or body field does not select a tenant, the context ends with the transaction |
| Frontend components | `frontend/src/**/*.test.ts(x)` (38 files) | map container, layers (each drawn from its source; archived geofences left off), controls, legend, popup, geofence editor (per-feature changes, strict-mode effects, Terra Draw restarting), the Terra Draw hook (a replaced map style starts a new instance), spatial tools, export panel, status, the API client and typed contracts, the map client's boundary |
| End to end | `test_end_to_end.py`, `frontend/e2e/map.e2e.ts` | the MVP scenario below |
| Pipeline | `backend/tests/pipeline` | OSM tag rules, file QA, byte-identical builds, an SLD99 source built end to end, ogr2ogr and pyproj agreeing, control points |
| Performance | `test_enrichment_indexes.py`, `test_spatial_query_regression.py`, `app.tools.benchmark` | index use at 20 000-row scale, a constant number of statements per event; latency and plans ([performance.md](performance.md)) |

### The MVP scenario, end to end

`backend/tests/integration/test_end_to_end.py` walks the whole scenario over HTTP; the browser test adds
the map.

| Step | Checked by |
|---|---|
| 1. A spatial event is submitted | `POST /geo/v1/enrich` for the tenant (`X-GIS-Tenant-Id`) |
| 2. Location is validated | swapped axes answer `422 invalid_coordinate` with `likelySwapped`; a bow-tie polygon answers `422 invalid_geometry`; neither is stored |
| 3. Geo-context enrichment executes | `200` with a `geo-context/1` document naming the release |
| 4. Administrative context | province, district and DS division codes and names |
| 5. Nearby settlement | nearest settlement with its distance |
| 6. Nearby road | nearest road with its distance |
| 7. Zone intersections | a sanctuary and two overlapping risk zones, each `within` |
| 8. Geofence hits | the geofence created in the scenario, at version 1 |
| 9. Persisted and returned | the stored document equals the returned one |
| 10. Event appears on the map | the event layer's request (`GET /geo/v1/events` by viewport) returns it; in the browser, the event is drawn, selected and its popup shows its context |
| 11. Spatial queries retrieve it | events by viewport, by geofence hit and by administrative area; containment and within-distance queries at its position |
| 12. Geofence management | create (API and editor), read, replace with a version (409 on a stale one), hits change for new events while stored hits stay, archive; another tenant sees none of it |

### Boundary cases

| Case | Tests |
|---|---|
| 499 m, 500 m, 501 m | `test_enrichment_engine.py::test_distance_threshold_of_500_m` (settlement, road, device, circle geofence at each distance, positions found by bisection with the database's own transformation), `test_spatial_query_api.py::test_a_feature_at_or_within_the_distance_is_included` / `test_a_feature_beyond_the_distance_is_left_out`, `test_spatial_query_regression.py::test_a_distance_threshold_is_inclusive_to_the_metre`, `test_postgis_regression.py::test_500_m_threshold_is_exact_in_the_metric_crs`, `test_spatial_model.py::test_distance_threshold_is_inclusive` |
| Exactly on a polygon boundary | `test_geo_context.py::test_point_on_shared_boundary_is_flagged_and_resolved_deterministically`, `test_boundary_vertex_and_edge_points_are_inside`, `test_enrichment_engine.py::test_zone_boundaries_are_inclusive`, `test_polygon_geofence_edge_is_inside`, `test_spatial_query_api.py::test_a_point_on_a_boundary_lies_in_both_areas`, `test_reverse_geocoding_names_the_area_on_a_boundary_deterministically`, `frontend/src/geo/geometry.test.ts` |
| Invalid polygons | `test_enrich_api.py::test_invalid_polygons_are_explained`, `test_enrichment_engine.py::test_invalid_coordinates_are_rejected_and_nothing_is_stored`, `test_spatial_model.py::test_invalid_reference_polygon_is_repaired_and_logged`, `test_invalid_geofences_are_rejected`, `test_spatial_query_api.py::test_an_invalid_geometry_is_refused_with_the_reason`, `test_geo_context.py::test_repaired_bow_tie_zone_is_usable`, pipeline `test_rules.py` (file QA) |
| Swapped coordinates | `test_enrich_api.py::test_swapped_coordinates_are_explained`, `test_spatial_query_api.py::test_swapped_axes_are_named_as_the_likely_mistake`, `test_reference_loader.py` (rejected with the reason), `test_end_to_end.py` |
| Empty spatial result | `test_enrichment_engine.py::test_nothing_within_the_search_radii`, `test_event_outside_every_zone`, `test_geo_context.py::test_point_outside_all_polygons_has_no_admin_areas`, `test_spatial_query_api.py::test_an_empty_answer_is_an_empty_collection` (within-distance, nearest, contains), `test_end_to_end.py` (events outside the viewport) |
| Multiple overlapping zones | `test_enrichment_engine.py::test_event_inside_several_zones`, `test_area_event_across_several_zones_intersects_them`, `test_spatial_query_api.py::test_overlapping_zones_are_all_returned`, `test_end_to_end.py` |

## Fixtures

* `data/fixtures/synthetic_habarana`: constructed geometry with known answers (shared boundaries, an
  enclave, overlapping zones, a seasonal zone, a bow-tie polygon, rejected features).
* `data/fixtures/lka_open`: an extract of open data (geoBoundaries, Natural Earth).
* Operational data is created by the tests through the runtime login, so row-level security applies
  (`backend/tests/integration/spatial_world.py`).
* The development sample (`data/sample`) is what the browser tests and the benchmark run against.
