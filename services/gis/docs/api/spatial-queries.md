# Spatial query API: layers, queries, events and operational objects

The reusable geospatial capabilities of the platform (plan §7): what a layer holds, what lies within a
distance, what is nearest, what contains a geometry, where a position is, which events were observed
where, and the geofences, sites and device placements a tenant maintains.

The machine-readable contract is the OpenAPI document (`/openapi.json`). Every endpoint here answers a
question about **places and things on a map**. The GIS service produces spatial facts; deciding what
follows from them belongs to the services that consume them (see [ADR-0012](../adr/ADR-0012-gis-only-service-boundary.md)).

| Endpoint | What it answers |
|---|---|
| `GET /geo/v1/layers` | Which layers exist, and what can be asked of each |
| `GET /geo/v1/layers/{layer}/features` | The features of one layer, by viewport, attribute and instant |
| `POST /geo/v1/query/within-distance` | Which objects are within N metres of a geometry |
| `POST /geo/v1/query/nearest` | Which objects are closest to a geometry |
| `POST /geo/v1/query/contains` | Which areas contain a geometry |
| `GET /geo/v1/reverse` | Where a position is (administrative hierarchy, nearest settlement and road) |
| `GET /geo/v1/events` | Event locations in a time window and area |
| `/geo/v1/geofences` | The tenant's geofences (create, read, replace, retire) |
| `/geo/v1/sites` | The tenant's installation sites |
| `/geo/v1/devices/{id}/placement` | Where one device is, and what it observes |
| `GET /geo/v1/layers/{layer}/export`, `GET /geo/v1/events/export` | A whole selection as one GeoJSON file |
| `GET /geo/v1/audit/entries` | The tenant's audit log |
| `GET /geo/v1/me` | The caller's permissions and tenant |

## Conventions

* **Geometry** is GeoJSON (RFC 7946): WGS84, `[longitude, latitude]`, `Point`, `LineString`, `Polygon`
  and their `Multi` forms. `GeometryCollection` is not accepted, and neither is a `crs` member - RFC 7946
  removed it. A request may state `"crs": "EPSG:4326"` (or `CRS84`, or the OGC URNs) for clarity; any
  other value is refused.
* **Distances** are metres on the SLD99 / Sri Lanka Grid 1999 plane (EPSG:5235), rounded to 0.01 m in
  answers. Thresholds are **inclusive**: with `distanceM: 500`, features at 499 m and 500 m are returned
  and one at 501 m is not.
* **Containment** is evaluated on the WGS84 geometry and includes the boundary: a point on the edge of a
  district, a zone or a geofence is inside it.
* **Positions** outside the service area (Sri Lanka and its nearshore waters, `GET /geo/v1/service-area`)
  are refused; when the swapped axes would be inside it, the problem says `likelySwapped`.
* **Reference data** is versioned: `refDataRelease` selects a published release, the current one by
  default, and every answer that comes from reference data names the release it used.
* **Operational data** belongs to a tenant: the one the request acts for (`X-GIS-Tenant-Id`, else the
  platform's organisation `GIS_TENANT_ID`). `tenantId` may be omitted; if given, it must be that tenant.
* **Errors** are RFC 9457 problem details (`application/problem+json`) with
  `type: urn:gis-core-service:problem:<code>` and a `requestId`.

### Access

No credentials: the GIS is reached only through the main platform, which owns sign-in
([ADR-0019](../adr/ADR-0019-platform-instance-without-own-authentication.md)). Each operation still
names the permission it exercises (`x-gis-permissions` in the OpenAPI document); every request has them
all ([../security.md](../security.md#2-permissions)).

### Audit

Every spatial question, reverse geocoding, read of tenant data (operational layers, geofences, sites,
placements, events) and export is recorded in the audit log in the transaction that answers it, with the
caller, the tenant, the parameters, the result count and a 0.001° extent of the geometry; changes are
recorded by the database. Reading reference layers by viewport is not recorded. See
[../security.md](../security.md#5-audit).

### Paging

Collections are paged with an opaque cursor, never an offset: the answer carries `nextCursor`, which is
passed back as `cursor` with **every other parameter unchanged**. A cursor used with different filters is
refused (`invalid_cursor`) rather than silently answering from another result set. `limit` defaults to
100 and is capped at 1000.

```http
GET /geo/v1/layers/ref.settlement/features?bbox=80.6,7.9,80.9,8.2&limit=100
GET /geo/v1/layers/ref.settlement/features?bbox=80.6,7.9,80.9,8.2&limit=100&cursor=eyJrIjoi...
```

## `GET /geo/v1/layers`

The catalogue: every published layer (`meta.layer`) with the geometry it holds, the CRS it is served in
(always EPSG:4326) and the one distances are measured in (EPSG:5235), whether it is tenant-scoped, and
what this API can do with it.

```json
{
  "layers": [
    {
      "code": "ref.settlement",
      "name": "Settlements",
      "description": "Cities, towns and villages as points or footprints.",
      "layerGroup": "reference",
      "geometryTypes": ["POINT", "MULTIPOLYGON"],
      "srid": 4326, "metricSrid": 5235,
      "tenantScoped": false,
      "defaultSharingPolicy": null,
      "updateFrequency": "quarterly",
      "nominalAccuracyM": 100.0,
      "queryable": true,
      "capabilities": ["features", "within_distance", "nearest", "contains"],
      "filters": ["type", "adminAreaId"],
      "properties": ["name", "nameSi", "nameTa", "settlementType", "population", "populationYear",
                     "basis", "adminAreaId"],
      "timeFiltered": false,
      "attribution": ["Made with Natural Earth"],
      "exportable": true
    }
  ],
  "refDataRelease": "ref-2026.09-lka-open",
  "attribution": ["Made with Natural Earth", "OCHA ROAP; Survey Department of Sri Lanka (CC BY 3.0 IGO); ..."]
}
```

`attribution` is what the licences of the layer's sources in the current release require to be shown
with the data (the catalogue's list covers all layers, without repeats); `exportable` is false when a
source does not allow redistribution, and exports of the layer are then refused. Where each dataset comes
from is in `GET /geo/v1/releases/{code}` ([releases.md](releases.md)).

`capabilities` is what the other endpoints accept for that layer; `contains` appears only for layers with
areas. `filters` and `properties` name the attribute filters it accepts and the feature properties it
returns - a filter a layer does not have is **rejected**, not ignored, so a typo cannot silently widen a
result set.

## `GET /geo/v1/layers/{layer}/features`

Features of one layer as a GeoJSON `FeatureCollection`.

| Parameter | Meaning |
|---|---|
| `bbox` | Viewport as `minLon,minLat,maxLon,maxLat` in WGS84 degrees |
| `type`, `status`, `level`, `code`, `parentId`, `adminAreaId`, `siteId`, `deviceId`, `refCode`, `severity`, `managingAuthority`, `geometryMethod` | The attribute filters the catalogue lists for the layer |
| `nameContains` | Case-insensitive substring of the feature name (`%` and `_` are literal) |
| `at` | Instant the layer's validity period must contain (risk zones, geofences, fields of view); default now |
| `refDataRelease` | Published release to read; only for reference layers, since tenant data is not versioned by release |
| `tenantId` | Tenant whose features to read (operational layers) |
| `includeGeometry` | `false` returns properties only - much smaller for boundary layers |
| `limit`, `cursor` | Paging |

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "0199f3d2-...",
      "geometry": {"type": "MultiPolygon", "coordinates": [[[[80.745, 8.025], "..."]]]},
      "properties": {"name": "Fixture Town", "settlementType": "town", "population": 4200, "basis": "footprint"}
    }
  ],
  "count": 1,
  "layer": "ref.settlement",
  "nextCursor": null,
  "refDataRelease": "ref-2026.09-fixture"
}
```

Operational layers (`ops.site`, `ops.device`, `ops.device_field_of_view`, `ops.geofence`) show the
tenant's own features and those other tenants have shared with it, and nothing else.

## `POST /geo/v1/query/within-distance`

Objects of one layer within `distanceM` of a geometry, nearest first, each with `distanceM` in its
properties. The distance is measured to the feature itself - the edge of a settlement footprint, the line
of a road, the circle of a geofence - not to a centroid or a bounding box.

```http
POST /geo/v1/query/within-distance
Content-Type: application/json

{
  "target": "ref.facility",
  "geometry": {"type": "Point", "coordinates": [80.7513, 8.0342]},
  "distanceM": 5000,
  "filters": {"type": "hospital"},
  "limit": 50
}
```

The answer is a `FeatureCollection` with `nextCursor` for the next page. For a handful of objects,
`/query/nearest` is cheaper.

## `POST /geo/v1/query/nearest`

The `limit` nearest objects (default 10, at most 100), bounded by `maxDistanceM` (default 25 km, at most
100 km). The bound is what keeps the search on the spatial index, and what keeps the answer meaningful.
Nearest queries are not paged.

```json
{"target": "ops.device", "geometry": {"type": "Point", "coordinates": [80.75, 8.03]}, "limit": 5}
```

## `POST /geo/v1/query/contains`

Areas of one layer that contain a geometry: point-in-polygon, and the same question for lines and areas.

* `mode: "covers"` (default): areas that contain the whole geometry, boundary inclusive.
* `mode: "intersects"`: areas that share any point with it.

Each feature carries `relation`: `within` when the whole geometry lies inside, `intersects` when it
crosses the boundary.

```json
{"target": "ref.protected_area", "geometry": {"type": "Point", "coordinates": [80.758, 8.015]}}
```

Circle and corridor geofences are tested against their **definition and radius**, so a point exactly at
the radius is inside and a point a metre beyond it is not. For a line or area geometry, a circle compares
the farthest point of the geometry from its centre with the radius (exact), and a corridor compares the
geometry with a finely drawn buffer of its centre line (within a centimetre of the true shape at the
largest half-width).

## `GET /geo/v1/reverse`

Where a position is.

```http
GET /geo/v1/reverse?lon=80.7513&lat=8.0342
```

```json
{
  "point": {"type": "Point", "coordinates": [80.7513, 8.0342]},
  "admin": {
    "province": {"id": "...", "code": "LK7", "name": "North Central Province", "level": 1, "levelName": "province"},
    "district": {"id": "...", "code": "LK71", "name": "Anuradhapura", "level": 2, "levelName": "district"},
    "dsDivision": {"...": "..."},
    "gnDivision": {"...": "..."},
    "codes": {"l1": "LK7", "l2": "LK71", "l3": null, "l4": null},
    "onBoundary": false
  },
  "nearestSettlement": {"id": "...", "name": "Habarana", "settlementType": "town", "basis": "point", "distanceM": 512.34},
  "nearestRoad": {"id": "...", "name": "Habarana - Trincomalee", "class": "A", "refCode": "A11", "distanceM": 48.9},
  "settlementRadiusM": 25000.0,
  "roadRadiusM": 10000.0,
  "missingLayers": [],
  "refDataRelease": "ref-2026.09-lka-open",
  "computedAt": "2026-09-21T09:15:04.221Z"
}
```

Reference data only: the answer is the same for every tenant, needs no tenant, and nothing is stored. On
a shared boundary the area with the lowest code is chosen and `onBoundary` is `true`, so the answer is
deterministic. `missingLayers` names reference layers with no features in the release, so an empty answer
for one of them is not mistaken for "nothing is there".

## `GET /geo/v1/events`

Event locations of one tenant as a `FeatureCollection`, newest first.

| Parameter | Meaning |
|---|---|
| `from`, `to` | Window on `observedAt`; `from` inclusive, `to` exclusive. Default: the last 24 hours, at most 31 days |
| `bbox` | Viewport |
| `eventType`, `eventSubtype`, `sourceType`, `deviceId` | Attribute filters |
| `geofenceId` | Only events whose geo-context recorded a hit on that geofence |
| `adminAreaId`, `adminAreaCode` | Only events the geo-context placed in that administrative area (any level) |
| `tenantId`, `includeGeometry`, `limit`, `cursor` | As elsewhere |

The window is bounded because event storage is partitioned by month of `observedAt`; a bounded window is
what keeps a query on a few partitions. Each feature carries the event's own attributes plus `admin` (the
codes of the four administrative levels) and `refDataRelease` from its geo-context, and the answer echoes
the `window` it used.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "evt-2026-09-000123",
      "geometry": {"type": "Point", "coordinates": [80.749, 8.037]},
      "properties": {
        "eventId": "evt-2026-09-000123", "tenantId": "wildlife-dept",
        "observedAt": "2026-09-14T03:02:10Z", "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor", "locationSource": "sensor", "geometryKind": "point",
        "admin": {"l1": "LK7", "l2": "LK71", "l3": null, "l4": null},
        "refDataRelease": "ref-2026.09-lka-open"
      }
    }
  ],
  "count": 1,
  "layer": "geo.event_location",
  "nextCursor": null,
  "window": {"from": "2026-09-14T00:00:00Z", "to": "2026-09-15T00:00:00Z"}
}
```

## Geofences

A geofence is a named area with a validity period, owned by one tenant.

| Operation | |
|---|---|
| `GET /geo/v1/geofences` | List, filtered by `status`, `kind`, `bbox`, `nameContains`, `at`, `ownedOnly`; paged |
| `POST /geo/v1/geofences` | Create (`201`, `Location` header) |
| `GET /geo/v1/geofences/{id}` | Read |
| `PUT /geo/v1/geofences/{id}` | Replace, based on the `version` that was read |
| `DELETE /geo/v1/geofences/{id}` | Archive; `?purge=true` deletes irreversibly; `?version=` makes it conditional |

**Shapes.** The geometry the author defines is what is stored and what hits are tested against:

```json
{"kind": "polygon",  "geometry": {"type": "Polygon", "coordinates": [[[80.74, 8.02], "..."]]}}
{"kind": "circle",   "geometry": {"type": "Point", "coordinates": [80.7487, 8.0356]}, "radiusM": 750}
{"kind": "corridor", "geometry": {"type": "LineString", "coordinates": [[80.70, 8.01], [80.80, 8.01]]}, "radiusM": 50}
```

A circle's radius is at most 50 km, a corridor's half-width at most 5 km. The definition must be
geometrically valid and lie inside the service area; the database derives the search polygons from it in
EPSG:5235, and circle and corridor hits are tested against the definition and the radius, so they are
exact rather than an approximation of the stored polygon.

```json
{
  "name": "Habarana junction watch zone",
  "definition": {"kind": "circle", "geometry": {"type": "Point", "coordinates": [80.7487, 8.0356]}, "radiusM": 750},
  "status": "active",
  "effectiveDuring": {"from": "2026-09-01T00:00:00Z", "to": null},
  "sharingPolicy": "shared",
  "sharedWithTenants": ["forest-dept"],
  "externalId": "WZ-007",
  "attributes": {"team": "north"}
}
```

**Status and period.** Only `active` geofences produce geo-context hits, and only while
`effectiveDuring` contains the event's observation time. `draft` and `suspended` geofences are stored but
not tested; `archived` ones are retired.

**Versioning.** Every change increments `version`. A replace states the version it is based on and is
refused with `409 version_conflict` (carrying `currentVersion`) if the geofence has moved on. Stored
geo-context hits name the geofence version they were computed against, which is what keeps an earlier hit
interpretable after the geofence changes.

**Ownership and sharing.** Only the owning tenant can change or delete a geofence, even one shared for
reading: the attempt is refused with `403 not_owner` rather than silently doing nothing. `sharingPolicy`
is `private` (owner only), `shared` (also `sharedWithTenants` and authority tenants) or `authority_only`.
A private geofence of another tenant is not visible at all - reads answer `404`.

**Retiring.** `DELETE` archives, which keeps the row: hits computed earlier name this geofence, and an
operator looking at them should still find it. `?purge=true` is for a geofence created by mistake.

## Sites and device placements

`GET|POST /geo/v1/sites`, `GET|PUT|DELETE /geo/v1/sites/{id}` manage installation sites: a name, a point
position with its source and accuracy, a type and a status. `DELETE` decommissions the site (`?purge=true`
deletes it), which keeps it readable for the devices and events that refer to it.

`PUT /geo/v1/devices/{id}/placement` records where a device is. The identifier in the path is the
device's id, which the client chooses:

* the device does not exist yet: it is registered with that id, and the answer is `201`
* it exists: its placement is replaced, and the answer is `200`. The request states the `version` that
  was read; a stale version is refused with `409`

```json
{
  "name": "HB-CAM-01",
  "deviceType": "camera",
  "position": {"type": "Point", "coordinates": [80.752, 8.040]},
  "positionSource": "gps",
  "mountingHeightM": 6.5,
  "siteId": "0199f3d2-...",
  "fieldOfView": {"method": "modelled", "bearingDeg": 225, "fovDeg": 70, "rangeM": 600},
  "version": 3
}
```

`fieldOfView` closes the period in effect and starts a new one. A `modelled` field of view is the sector
the database computes from bearing, angle and range, and it follows the device when it moves; a
`surveyed` one is the polygon that was supplied and keeps its geometry. `GET .../placement?at=` reads the
placement with the field of view that was in effect at that instant.

## Exports

`GET /geo/v1/layers/{layer}/export` takes the selection parameters of `/features` (`bbox`, the layer's
filters, `nameContains`, `at`, `refDataRelease`, `tenantId`) and `GET /geo/v1/events/export` those of
`/events` (window, `bbox`, type, source, device, geofence, administrative area, `tenantId`). The answer is
one GeoJSON `FeatureCollection` (`application/geo+json`, `Content-Disposition: attachment`) with
`exportedAt`, `tenantId` for tenant data, `refDataRelease` and `attribution` (keep it with the data) for
reference data and `window` for events. Reference data whose licence does not allow redistribution is not
exported: `403 export_not_permitted`, naming the `sources` and the `refDataRelease`.

An export is the complete selection or nothing: more than `GIS_EXPORT_MAX_FEATURES` (10 000) features is
refused with `422 export_too_large` rather than cut short. Exports need `data:export` together with
`map:read` (layers) or `events:read` (events), and every export is audited with its parameters and count.

## `GET /geo/v1/audit/entries`

The tenant's audit log, newest first, keyset-paged: `category` (`search`, `sensitive_query`, `export`,
`change`, `release`), `operation` (e.g. `geofence.archive`), `actorSubject`, `from`, `to`, `limit`,
`cursor`, `tenantId`. Entries of the tenant the request acts for; reading the log is itself recorded.

```json
{
  "items": [
    {
      "id": 4812, "occurredAt": "2026-09-23T10:15:02.113Z", "tenantId": "wildlife-dept",
      "category": "search", "operation": "query.within_distance", "target": "ops.device", "objectId": null,
      "actor": {"subject": "platform", "clientId": null},
      "crossTenant": false, "channel": "api", "requestId": "5f0c6f0f2f5c4b1f9a55c6f1d2a7e3b4",
      "dbUser": "gis_app", "geometryType": "POINT",
      "geometryExtent": {"type": "Polygon", "coordinates": [[[80.751, 8.029], [80.751, 8.03],
                         [80.752, 8.03], [80.752, 8.029], [80.751, 8.029]]]},
      "parameters": {"distanceM": 750, "filters": {}}, "resultCount": 2
    }
  ],
  "count": 1,
  "nextCursor": null
}
```

## `GET /geo/v1/me`

The caller as the service sees it - `subject` (`platform`), `clientId`, `permissions`, `tenants` (the one
the request acts for), `allTenants`, `defaultTenant` - so a client can offer only what the caller may use.

## Errors

| Status | `code` | When |
|---|---|---|
| 403 | `forbidden` | `tenantId` names a tenant other than the one the request acts for (`tenantId`) |
| 403 | `not_owner` | The object belongs to another tenant and is shared for reading only |
| 403 | `tenant_not_registered` | The request acts for a tenant the GIS service does not know |
| 403 | `export_not_permitted` | A source of the layer does not allow its data to leave the platform (`sources`, `refDataRelease`) |
| 404 | `layer_not_found` | `target` or `{layer}` is not a queryable layer (`queryableLayers` lists them) |
| 404 | `geofence_not_found`, `site_not_found`, `device_not_found` | No such object is visible to this tenant |
| 404 | `release_not_found` | `refDataRelease` does not exist |
| 409 | `version_conflict` | The object changed since `version` (`currentVersion` says what it is now) |
| 409 | `external_id_in_use` | Another object of this tenant already uses that `externalId` |
| 409 | `identifier_in_use` | The chosen device id is already taken |
| 409 | `field_of_view_overlap` | The new field of view overlaps a recorded period |
| 422 | `request_validation_error` | Schema violations, including an unsupported CRS and a `crs` member inside a geometry |
| 422 | `invalid_coordinate` | A position is outside WGS84 or the service area (`likelySwapped` when the axes look swapped) |
| 422 | `invalid_geometry` | Empty, self-intersecting or otherwise invalid geometry (`reason`) |
| 422 | `invalid_bbox` | `bbox` is not four ordered numbers, or does not overlap the service area |
| 422 | `invalid_cursor` | The cursor is malformed, or belongs to another query |
| 422 | `unsupported_filter` | A filter the layer does not have (including `at` on a layer without a validity period and `refDataRelease` on tenant data), or a value outside its set (`supportedFilters`, `allowedValues`) |
| 422 | `unsupported_query` | Containment asked of a layer without areas (`capabilities`) |
| 422 | `unknown_site` | `siteId` does not name a site of this tenant |
| 422 | `time_window_too_large` | The event window is longer than 31 days (`maxWindowDays`) |
| 422 | `release_not_usable` | The release is a draft |
| 422 | `export_too_large` | The selection holds more features than one export may (`maxFeatures`, `GIS_EXPORT_MAX_FEATURES`) |
| 503 | `reference_data_unavailable` | No published reference data release |
| 503 | `authentication_unavailable` | Authentication is not configured, or the identity provider's keys cannot be fetched |

## How a query is executed

1. The layer is resolved in the registry (`app/spatial/layers.py`). Unknown layers are refused before any
   SQL exists.
2. The request is validated: CRS expectation, geometry (RFC 7946, service area, OGC validity), bounding
   box, the filters the layer actually has, the paging cursor.
3. The scope is settled: a published reference data release, or the tenant whose row-level security
   context the transaction runs in.
4. One parameterised statement runs. Every table, column and expression in it comes from the registry;
   every value is a bound parameter. Containment on reference areas goes through the subdivided parts in
   `ref.area_part`, proximity through the KNN operator on the EPSG:5235 index, and tenant tables state the
   bounding-box test explicitly so that row-level security cannot hide the index
   ([ADR-0014](../adr/ADR-0014-geo-context-enrichment.md)).
