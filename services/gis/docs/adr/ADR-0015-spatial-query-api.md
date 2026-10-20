# ADR-0015: The spatial query API

* Status: accepted
* Date: 2026-09-21
* Refines: plan §7 (API surface), §9 (tenant isolation); ADR-0012 (service boundary), ADR-0013 (data
  model), ADR-0014 (enrichment)

## Context

The platform needs generic geospatial capabilities: what a layer holds, what is near a place, what
contains a place, where a position is, and which events were observed where. Findings while designing
them:

* The obvious shape for these endpoints is one per question a consumer has ("who is within 500 m"), which
  would pull recipients, subscriptions and messaging into the GIS service. ADR-0012 keeps them out.
* A query API that takes a layer name, filters and an ordering is a SQL generator by another name. Written
  naively it interpolates client input into statements.
* Offset paging over spatial results is both wrong (rows move between pages when data changes) and slow at
  depth.
* Reference data is versioned by release. An answer that does not name its release cannot be reproduced.
* Tenant data is protected by row-level security, so a query that forgets the tenant returns nothing
  rather than someone else's rows - but a *write* that forgets whose object it is would silently do
  nothing, which is worse than refusing.
* FastAPI expands a Pydantic model into individual query parameters only while that model is the sole
  source of query parameters for the operation; a `tenantId` dependency alongside it silently turns the
  whole model into one opaque parameter.

## Decision

1. **Generic questions, not answers about people.** The API exposes `within-distance`, `nearest`,
   `contains`, `features`, `reverse` and `events`. There is no recipient lookup, notification location or
   "notify users within X metres" endpoint, and no endpoint documentation mentions messaging; a test
   asserts both against the generated OpenAPI document.
2. **A whitelisted layer registry.** `app/spatial/layers.py` is the only source of schema, table, column
   and expression names in generated SQL, and it declares what each layer offers: its filters and their
   allowed values, its feature properties, its validity period, whether it has areas, and how containment
   and distance are evaluated for it. Requests select a layer, a filter or a property *by name*; the name
   is looked up and the constant found is what reaches SQL. Every value is a bound parameter. The registry
   is shape-checked at import, and a unit test asserts that every name in it is a real column of the
   mapped schema. `GET /geo/v1/layers` publishes the same registry, so a client can discover exactly what
   the service will accept.
3. **Filters are rejected, not ignored.** A filter a layer does not have, a value outside its enumerated
   set, an `at` on a layer without a validity period, a name search on a layer without names, or
   containment on a layer without areas are all 422 with the supported alternatives in the problem. A
   typo cannot silently widen a result set.
4. **Keyset paging with a query-bound cursor.** Collections are ordered by id (features, containment), by
   distance and id (proximity) or by observation time and id (events), and the cursor carries that key
   plus a fingerprint of the query it belongs to. A cursor used with other filters is refused. The cursor
   is opaque but grants nothing: its values are type-checked and bound, and the fingerprint is a hash, not
   a signature.
5. **Release in the answer.** Every answer derived from reference data carries `refDataRelease`, and
   `refDataRelease` in the request pins a published release. Only published (or retired) releases can be
   read; a draft is refused. The rule lives in `app/services/releases.py` and is shared with enrichment,
   so a query and an event see the same data.
6. **Tenant from the token, refusal over silence.** `tenantId` selects among the tenants the token grants
   (or any tenant with `gis:tenants:all`); with a single-tenant token it may be omitted. An operation on
   tenant data without a tenant answers 400 `tenant_required`. Reads of another tenant's private objects
   are 404; changes to an object shared for reading are 403 `not_owner`, so a caller can tell "not there"
   from "not yours". New scopes `gis:read` and `gis:write` separate reading from changing.
7. **Versions on operational objects.** A replace states the version it read; a mismatch is 409 with the
   current version. `DELETE` archives a geofence (decommissions a site) and `?purge=true` removes it,
   because stored geo-context hits name geofences and their versions.
8. **Geofences keep their definition.** A polygon, a circle (centre and radius) or a corridor (centre line
   and half-width) is stored as given and validated (WGS84, inside the service area, geometrically valid);
   the database derives the search polygons. Circle and corridor tests use the definition and the radius,
   never the derived polygon, so a point exactly at the radius is inside. For a line or area, a circle
   compares the farthest point of the geometry from its centre with the radius (`ST_MaxDistance`, exact),
   and a corridor compares it with a buffer of the centre line drawn at 512 segments per quarter circle,
   whose deviation from the true shape stays under a centimetre even at the largest half-width.
9. **Index-driven statements.** Proximity and containment run as a lateral subquery over the one-row query
   geometry, which is what lets PostgreSQL drive them from the spatial index; containment on reference
   areas goes through the subdivided `ref.area_part`; tenant tables state the bounding-box test (`&&`)
   explicitly (ADR-0014). Regression tests run `EXPLAIN` with sequential scans disabled and fail on a plan
   that still cannot use the index.
10. **Query parameters as one model per operation.** Endpoints with a Pydantic query-parameter model carry
    `tenantId` inside that model rather than in a dependency, because FastAPI otherwise collapses the model
    into a single opaque parameter and the OpenAPI document stops describing the API.

## Consequences

* Adding a layer to the API is a registry entry plus its documentation; nothing in the repository or the
  routers changes. Exposing a column means naming it in the registry, which is also where the OpenAPI
  catalogue gets it from.
* `bbox` filters use `&&` plus an exact intersection, so a viewport answer is the features that really
  overlap the box, not those whose bounding box does.
* Cursors cannot be reused across releases, filters or windows. Clients that change a filter start again -
  which is the honest behaviour, since the result set is a different one.
* Nearest queries are bounded (`maxDistanceM`, default 25 km) and not paged. Unbounded nearest searches
  cannot use the index under row-level security and rarely mean what the caller wants.
* Event queries need a bounded window (at most 31 days, 24 hours by default) because `geo.*` is
  partitioned by month; a longer window is refused rather than scanning every partition.
* Answers about tenant data are `Cache-Control: no-store`; the catalogue and reverse geocoding are
  cacheable for a minute.
* Containment on a corridor buffers its centre line finely (512 segments per quarter circle) for a line or
  area query geometry. That is more work per candidate row than the stored 32-segment polygon, but it is
  paid only for the few geofences whose bounding box already overlaps, and it keeps the answer inside the
  centimetre the API rounds to. A point - the common case - needs no buffer at all.
* `refDataRelease` on an operational layer, like any other parameter a layer does not have, is refused
  rather than ignored; tenant data is not versioned by release.
