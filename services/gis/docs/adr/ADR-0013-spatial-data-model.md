# ADR-0013: Spatial data model conventions

* Status: accepted
* Date: 2026-09-16
* Refines: plan ADR-02 (CRS), ADR-09 (tenancy); follows ADR-0012 (GIS-only boundary)

## Context

The authoritative PostGIS model (migrations 0002-0005) had to settle several questions the plan left
open. Measurements from the foundation and from this work:

* A WGS84 -> SLD99 -> WGS84 round trip moves a point by about 2 mm. A point on a polygon edge, or on a
  sector apex, is therefore no longer exactly on it after transforming both sides.
* PostGIS `ST_Buffer` places polygon vertices on the circle, so a buffered circle is slightly smaller than
  the circle (up to 0.03 % of the radius with 32 segments per quarter): points near the edge but within
  the radius fall outside the polygon.
* `ST_IsValid(g)` emits a NOTICE per invalid row; `ST_IsValid(g, 0)` gives the same answer silently.
* Every PostGIS function needed for derived columns (`ST_Transform`, `ST_PointOnSurface`, `ST_Dimension`,
  `GeometryType`, `Box3D`) is IMMUTABLE, so stored generated columns are possible.
* A partitioned table without a default partition rejects rows for missing months with SQLSTATE 23514.

## Decision

1. **Twin columns.** Every geometry is stored as `geom` (EPSG:4326, canonical) and `geom_metric`
   (EPSG:5235, stored generated column). Both carry GiST indexes.
2. **Containment in EPSG:4326, measurement in EPSG:5235.** Point-in-polygon and polygon relations use
   the canonical geometry, boundary inclusive. Distances, radii, buffers, areas and nearest-neighbour
   ordering use the metric column. Distance thresholds are inclusive.
3. **Geofence search polygons circumscribe.** Circle and corridor geofences keep their definition; the
   derived `geom_metric` is buffered at `r / cos(pi / 128)` so that it contains the exact buffer and the
   index cannot miss a hit. A hit is decided by `ST_DWithin` on the definition with the exact radius.
   The sector of a modelled field of view is built in metres, but its apex is the original device point.
4. **Validity in the database.** Every geometry column has CHECK constraints for validity, non-emptiness
   and the Sri Lanka envelope. Reference polygons are repaired and logged by trigger; tenant geometries
   and events are rejected with the reason.
5. **Releases are immutable once published**, enforced by triggers; lineage is a row per loaded file,
   linked to features by a composite `(load_id, release_id)` key. Sources that do not permit commercial
   use need a recorded permission.
6. **Tenancy by composite keys and RLS.** Tenant-owned tables expose `UNIQUE (id, tenant_id)` and child
   tables reference it, so cross-tenant links are impossible even for the table owner. Read access
   follows `sharing_policy`; writes are owner-only. Geofence hits are the exception by design: they are
   snapshots without a foreign key, because a shared geofence belongs to another tenant, and a hit must
   not stop that tenant from changing or deleting it.
7. **Monthly event partitions without a default partition.** Operators prepare months in advance and
   before historical imports; the runtime login may create a month on demand only for observations from
   13 months back to 1 day ahead, through a security definer function, in a separate short transaction.
8. **Downgrades never discard data.** A downgrade fails while any table it would drop holds rows.

## Consequences

* Two geometry columns per row cost storage (roughly double for geometry data) and write time; in return
  metric queries use indexes without transforming at query time.
* Topological tests and metric tests can disagree by millimetres for points within millimetres of a
  boundary. This is documented and below any accuracy the data supports.
* A geofence's stored `geom` for circles is up to 0.03 % larger than the circle; it is for display and
  indexing only. The service must never use it to decide circle or corridor hits.
* Operators need a job (or the service's on-demand path) to prepare event partitions and a retention
  procedure that drops old partitions child tables first (hits, context, then locations).
* Reference data must be loaded by the migration login; the runtime login can only read it.
* Model/migration parity, the partition rules, RLS and the release rules are covered by integration tests
  that run against PostgreSQL 18 + PostGIS 3.6.
