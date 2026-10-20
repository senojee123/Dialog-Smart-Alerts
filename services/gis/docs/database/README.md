# Spatial data model

PostgreSQL 18 + PostGIS 3.6. The Alembic revisions in `db/migrations/versions` are authoritative;
the ORM models in `backend/app/models` mirror them and a test fails on any difference.

| Document | Content |
|---|---|
| This file | Design rules and the reasons for them |
| [SCHEMA.md](SCHEMA.md) | Every table, column, constraint, index, trigger, policy and function (generated) |
| [ERD.md](ERD.md) | Entity-relationship diagram (generated, Mermaid) |
| [ADR-0013](../adr/ADR-0013-spatial-data-model.md) | Decisions: CRS twins, containment CRS, geofence search polygons, releases, partitions |
| [ADR-0014](../adr/ADR-0014-geo-context-enrichment.md) | Enrichment: one lookup statement, leakproof `&&` for row-level security, document layout |

Regenerate the two generated documents after changing a migration (from `backend/`, with the `GIS_DB_*`
variables pointing at a database migrated to head):

```bash
python ../db/tools/generate_schema_docs.py          # write
python ../db/tools/generate_schema_docs.py --check  # CI: fail when out of date
```

## Revisions

| Revision | Creates |
|---|---|
| `20260915_0001` | PostGIS check, schemas, default privileges, `meta.current_tenant_id()` |
| `20260915_0002` | `btree_gist`; `meta.tenant`, `meta.data_source`, `meta.ref_data_release`, `meta.layer`, `meta.dataset_load`, `meta.geometry_repair`; shared spatial and trigger functions |
| `20260915_0003` | `ref.admin_area`, `ref.settlement`, `ref.facility`, `ref.road`, `ref.water_body`, `ref.protected_area`, `ref.risk_zone`, `ref.area_part` |
| `20260915_0004` | `ops.site`, `ops.device`, `ops.device_field_of_view`, `ops.geofence`, row-level security |
| `20260915_0005` | `geo.event_location`, `geo.event_geo_context`, `geo.event_zone_hit`, `geo.event_geofence_hit` (monthly partitions); partition functions `geo.create_event_partitions()`, `geo.prepare_event_partitions()` (operators) and `geo.ensure_event_partition()` (runtime, recent months) |
| `20260917_0006` | Geo-context document layout of plan §5.3 (`schema`, `insideZones`, `refDataRelease`, ...): new `ck_event_geo_context_document`, stored documents converted (both directions) |
| `20260923_0007` | `audit.entry` (append-only audit log with row-level security), `audit.coarse_extent()`, the stamping and append-only triggers, and change triggers on `ops.geofence`, `ops.site`, `ops.device` and `meta.ref_data_release` ([../security.md](../security.md#5-audit)) |
| `20260924_0008` | Reference data pipeline: licence review and redistribution on `meta.data_source`; release `purpose`; lineage on `meta.dataset_load` (licence snapshot, source reference and version, original file and checksum, retrieval time, CRS operation, geometry types, extent, accuracy, file QA); `meta.qa_run`, `meta.qa_finding` (waivers guarded and audited), `meta.release_artifact`, `meta.release_artifact_source`; `meta.release_fingerprint()`; the publish gate; view `meta.dataset_lineage` ([../reference-data/pipeline.md](../reference-data/pipeline.md)) |

Downgrades refuse to drop a table that still holds rows (`refuse_if_not_empty`), in the same spirit as
the foundation revision, which drops schemas with `RESTRICT`.

There are no notification, recipient or alert tables, and no columns for phone numbers, e-mail addresses
or push tokens. Tests enforce this (`test_no_alerting_or_notification_objects_exist`, and
`tests/integration/test_privacy.py`, which also holds every geometry column to a reviewed list).

## Geometry rules

**Two columns per geometry.** Every layer stores

* `geom`: canonical geometry, EPSG:4326 (WGS84, longitude/latitude), exactly as received or loaded, and
* `geom_metric`: a stored generated column `ST_Transform(geom, 5235)` in SLD99 / Sri Lanka Grid 1999.

Both have GiST indexes. Reference tables index `(release_id, geom)` and `(release_id, geom_metric)`
(`btree_gist`), so that searches stay fast when several releases are kept.

**Which CRS for which operation.**

| Operation | CRS | Why |
|---|---|---|
| Storage, API input and output (GeoJSON) | 4326 | Interoperability, RFC 7946 |
| Containment: admin areas, zones, polygon geofences | 4326 (`ST_Intersects`, `ST_Covers`) | The client's vertices keep their exact binary values, so a point on an edge or vertex stays on it. Transforming both sides can move such a point by nanometres to either side. |
| Distances, radii, buffers, areas, nearest neighbour (`<->`) | 5235 (`ST_Distance`, `ST_DWithin`, `ST_Buffer`, `ST_Area`) | Metres; SLD99 grid distances are within 250 ppm of geodesic distances on the island |
| Map tiles | 3857 | Web maps |

Boundaries are inclusive: a point on an admin boundary is in both areas (the geo-context picks the
lowest code and sets `onBoundary`), and a distance equal to a threshold is within it.

**Validity.** Every geometry column has three CHECK constraints: `ST_IsValid(g, 0)` (the two-argument
form reports no NOTICE per row), `NOT ST_IsEmpty(g)` and `meta.is_within_sri_lanka(g)`. The last one
requires SRID 4326 and an exact envelope (`Box3D`, double precision) inside lon 79.44-82.15,
lat 5.66-10.08, which catches `[lat, lon]` input: a swapped Sri Lankan position has a longitude of 6-10.
The application setting `GIS_SERVICE_AREA_BBOX` may narrow this envelope, never widen it.

**Invalid polygons.**

| Where | Behaviour |
|---|---|
| Reference data (loader, any SQL client) | Trigger `a20_normalise_geometry` repairs the polygon with `ST_MakeValid(..., 'method=structure')`, keeps the polygonal part, logs the original and both areas in `meta.geometry_repair`, and rejects the row (SQLSTATE 22023) when nothing polygonal is left. Lines and polygons are stored as multi-geometries. |
| Tenant geofences and surveyed fields of view | Rejected with the validity reason (SQLSTATE 22023). A user must see and fix the problem. |
| Event locations | Rejected by the application with the reason and location; the CHECK constraint is the backstop. |

**Geometry kinds.** Settlements are a point or a footprint (`geometry_basis`), water bodies a line or an
area (`geometry_kind`), events a point, line or area (`geometry_kind`, from `ST_Dimension`).

**Accuracy and source.** Reference rows carry `geometry_source` (survey, gps, digitised, imagery, osm,
derived, synthetic, unknown) and `geometry_accuracy_m`; sites and devices carry `position_source` and
`position_accuracy_m`; events carry `location_source` (device, estimated, sensor, external) and
`location_accuracy_m`. `meta.layer.nominal_accuracy_m` gives the typical accuracy of each layer.

## Reference data releases and lineage

* A release (`meta.ref_data_release`, code `ref-YYYY.MM[-suffix]`) moves draft -> published -> retired.
  Triggers enforce the transitions, refuse to publish while a load is still running, and make the rows
  of a published release immutable. A retired release can be purged. At most one release is current.
* Every source file becomes a `meta.dataset_load` row: data source, file name, SHA-256, source CRS,
  transformation, loader version, counts of loaded, repaired and rejected features, and timing. Features
  reference their load with a composite key `(load_id, release_id)`, so a feature can never claim a
  release its load does not belong to. Deleting a load deletes its features.
* `meta.data_source` records publisher, licence, attribution, share-alike, redistribution and the
  licence review. A source whose licence does not permit commercial use (WDPA, for example) cannot be
  registered without a `permission_reference`. The licence terms are copied into each
  `meta.dataset_load`, with the source reference and version, the original file and its checksum, the
  retrieval time, the source CRS and the coordinate operation, the geometry types, extent and nominal
  accuracy (view `meta.dataset_lineage`).
* A release has a purpose (`production`, `development`, `test`). It is published only when its latest
  database QA run (`meta.qa_run`, findings in `meta.qa_finding`) matches its content fingerprint
  (`meta.release_fingerprint()`) and has no unwaived errors; waivers need a reason, some checks cannot be
  waived, and every waiver is audited. Basemap files are recorded as `meta.release_artifact` with their
  sources.
* `ref.area_part` holds the area layers split with `ST_Subdivide` (at most 255 vertices), maintained by
  triggers, so point-in-polygon lookups touch small geometries instead of whole provinces.

## Operational data and tenancy

* `tenant_id` defaults to `meta.current_tenant_id()`, the transaction-local `gis.tenant_id`.
* Every change of a geofence, site or device is recorded in `audit.entry` by the trigger
  `z90_audit_change`, with the actor from the transaction context (`gis.actor_subject`, ...; the
  database login when there is none).
* Row-level security: owners read and write their rows. `sharing_policy = 'shared'` adds the tenants in
  `shared_with_tenants` and authority tenants as readers; `authority_only` adds authorities only.
  A field of view is visible exactly when its device is.
* Spatial indexes under row-level security: PostgreSQL turns a condition into an index condition on a
  table with policies only if its operator is LEAKPROOF. Queries on tenant tables therefore state the
  bounding-box test with `&&` explicitly, and the database initialisation marks PostGIS's `&&`
  (`geometry_overlaps`) LEAKPROOF (`db/admin/postgis-leakproof.sql`; re-apply after PostGIS updates;
  readiness check `tenant_spatial_indexes`).
* Composite foreign keys on `(id, tenant_id)` make cross-tenant links impossible (a device cannot be
  installed at another tenant's site, an event cannot name another tenant's device, even a shared one).
* `meta.tenant.is_active` controls authority status only; switching a tenant off is enforced where
  requests come from (the main platform, which names the tenant in `X-GIS-Tenant-Id`).
* `version` increments on every update (optimistic concurrency); `updated_at` is maintained by trigger.
* Modelled fields of view are computed by the database (`meta.sector_polygon`) from the device position,
  bearing (clockwise from grid north), angle and range. An open period follows the device when it moves;
  a closed period keeps its sector (close the current period before moving a device if the old view
  matters). Validity periods of one device cannot overlap (exclusion constraint).
* Geofences are defined as a polygon, a circle (point + `radius_m`) or a corridor (line + half-width).
  The trigger derives `geom_metric`, `geom` and `area_m2`. For circles and corridors, `geom_metric`
  circumscribes the exact buffer (vertices at `r / cos(pi/128)`), so the index never misses a hit; the hit
  itself is the exact, inclusive `ST_DWithin(definition_geom_metric, event, radius_m)`. The relation is
  `within` for a point hit, and for lines and areas when they lie inside the geofence (for circles and
  corridors: inside the buffer drawn with 32 segments per quarter circle), otherwise `intersects`.

## Events and geo-context

* The four `geo` tables are partitioned by month of `observed_at` in UTC (`<table>_pYYYYMM`). There is
  no default partition, so a missing month fails loudly:
  * operators (migration login) prepare months with `geo.prepare_event_partitions(from, to)`, from
    2000-01 up to 13 months ahead: a monthly job for the coming months, and before historical imports;
  * the runtime login may call `geo.ensure_event_partition(ts)` (security definer) only for recent
    observations, from 13 months back to 1 day ahead, so a client cannot trigger mass table creation.
    The service calls it in a separate short transaction when an insert reports a missing partition,
    then retries once. Creating a partition briefly locks the partitioned tables, which is why the
    monthly job should create them in advance;
  * the migration prepares the previous, current and next month.
* `observed_at` may not lie more than one day after `received_at` (clock skew); the service rejects such
  events before storing them.
* Partitions have row-level security enabled without policies: the runtime login reaches rows only
  through the partitioned tables, whose policies restrict them to the owning tenant.
* The key is `(tenant_id, event_id, observed_at)`. Re-sending an event replaces its location and
  discards the stored context, which described the old location; enrichment stores the new context in
  the same transaction, `record_location` alone leaves it to a later `recompute`.
* `geo.event_geo_context` stores the full document (`geo-context/1`, camelCase JSON; the constraint
  requires every member, the array members, and `schema`, `eventId`, `tenantId` and `refDataRelease`
  equal to the row's columns) plus frequently filtered values as columns: release, admin area ids and
  codes, nearest settlement and road with distances. The layout is described in
  [docs/api/enrichment.md](../api/enrichment.md). Hits are rows in `geo.event_zone_hit` and `geo.event_geofence_hit`
  (`within` or `intersects`). Geofence hits are snapshots (geofence id, owner, version) without a
  foreign key: a tenant's hit never prevents the owner of a shared geofence from changing or deleting
  it. Archive geofences rather than deleting them when their history matters.
* The admin hierarchy is looked up at the point itself, or at `ST_PointOnSurface` for line and area
  events. Zones, geofences and distances use the whole geometry.

## Indexes and query plans

Every spatial column that is searched has a GiST index (on `geom` and, where distances are measured, on
the SLD99 `geom_metric`); keys and the filtered columns of `geo.event_geo_context` and the hit tables have
B-tree indexes. Plans were checked with `EXPLAIN (ANALYZE, BUFFERS)` for every endpoint on the
development sample and for the event viewport query at 200 000 events a day
([performance.md](../performance.md)): all large-table accesses use an index, and no index was added by
the validation because none was justified by a plan. The one plan that degrades with volume is a
viewport query on a tenant table without the LEAKPROOF `&&` (44 ms instead of 11 ms at 200 000 events a
day), which is why the setting above is part of the database initialisation and of the readiness check.
`test_enrichment_indexes.py` and `test_spatial_query_regression.py` assert the index use at 20 000 rows.

## Fixtures

| Fixture | Release | Content |
|---|---|---|
| [`data/fixtures/lka_open`](../../data/fixtures/lka_open/SOURCES.md) | `ref-2026.09-lka-open` | Real, openly licensed data: all provinces and districts, DS divisions of Anuradhapura and Polonnaruwa, GN divisions of Palugaswewa (Habarana), Natural Earth towns, roads, rivers and reservoirs |
| [`data/fixtures/synthetic_habarana`](../../data/fixtures/synthetic_habarana/README.md) | `ref-2026.09-fixture` | Constructed geometry with known answers: shared boundaries, an enclave, a seasonal risk zone, a bow-tie polygon the database repairs, rejected features |

Operational fixtures (tenants, sites, devices, fields of view, geofences) are created by the integration
tests through the runtime login (`backend/tests/integration/spatial_world.py`).

For local development, the pipeline-built release `ref-2026.09-dev` and a sample tenant are in
[`data/sample`](../../data/sample/README.md).
