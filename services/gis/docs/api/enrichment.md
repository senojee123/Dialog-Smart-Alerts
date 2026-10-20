# Geo-context enrichment: `POST /geo/v1/enrich`

Stores where an event happened and returns its **geo-context** (`geo-context/1`): the admin hierarchy,
the nearest settlement and road with distances, the protected areas and risk zones it lies in, the
geofences it hits, nearby devices, and the reference data release used. This is the synchronous path of
plan §4.2 (event processor -> GIS). The machine-readable contract is the OpenAPI document
(`/openapi.json`, operation `enrichEvent`), whose examples come from a real run.

The response contains spatial facts only. The GIS service does not raise alerts, choose recipients or
deliver messages.

## Request

```http
POST /geo/v1/enrich?refDataRelease=ref-2026.09-lka-open HTTP/1.1
X-GIS-Tenant-Id: dialog-smart-alerts      (optional: default GIS_TENANT_ID)
Content-Type: application/json
```

| Member | Type | Required | Meaning |
|---|---|---|---|
| `eventId` | string, `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$` | yes | Producer's event id |
| `tenantId` | string, `^[a-z0-9][a-z0-9_-]{1,62}$` | yes | Tenant the event belongs to; must be the tenant the request acts for |
| `observedAt` | ISO 8601 with offset | yes | Observation time; stored and returned in UTC; at most 1 day in the future |
| `eventType` | string, dotted lower case | yes | e.g. `wildlife.elephant_detected` |
| `eventSubtype` | string | no | |
| `sourceType` | `device`, `sensor`, `external`, `manual` | yes | What produced the event |
| `deviceId` | UUID | for `sourceType` or `locationSource` `device` | Registered GIS device of the tenant |
| `sourceRef` | string (200) | no | Source id in the producer's system |
| `location` | GeoJSON geometry | unless `locationSource` is `device` | Point, LineString, Polygon or their Multi forms; WGS84 `[lon, lat]` |
| `locationSource` | `device`, `estimated`, `sensor`, `external` | yes | How the location was obtained |
| `locationAccuracyM` | number (0, 100000] | no | |
| `fieldOfViewId` | UUID | no | Field of view to record (default: the device's view in effect) |
| `metadata` | JSON object, up to 16 KiB, depth 8 | no | Stored with the event; not interpreted |

Query parameter `refDataRelease` (optional, `ref-YYYY.MM[-suffix]`) pins a published release, for
example to reproduce an earlier result. By default the current release is used.

```json
{
  "eventId": "evt-2026-09-000123",
  "tenantId": "wildlife-dept",
  "observedAt": "2026-09-14T08:32:10+05:30",
  "eventType": "wildlife.elephant_detected",
  "sourceType": "sensor",
  "sourceRef": "seismic-array-7",
  "location": {"type": "Point", "coordinates": [80.749, 8.037]},
  "locationSource": "sensor",
  "locationAccuracyM": 25,
  "metadata": {"confidence": 0.93, "herdSize": 4}
}
```

## Response `200`

The result of that request against the open-data fixture (ids shortened):

```json
{
  "schema": "geo-context/1",
  "eventId": "evt-2026-09-000123",
  "tenantId": "wildlife-dept",
  "observedAt": "2026-09-14T03:02:10Z",
  "locationSource": "sensor",
  "geometryKind": "point",
  "admin": {
    "province": {"id": "01a0...", "code": "LK-7", "name": "North Central Province", "nameSi": null, "nameTa": null, "level": 1, "levelName": "province"},
    "district": {"id": "01a0...", "code": "LK-71", "name": "Anuradhapura District", "...": "..."},
    "dsDivision": {"id": "01a0...", "name": "Palugaswewa", "...": "..."},
    "gnDivision": {"id": "01a0...", "name": "Habarana", "...": "..."},
    "codes": {"l1": "LK-7", "l2": "LK-71", "l3": "8540358B75401696350617", "l4": "91002919B21028929510394"},
    "onBoundary": false
  },
  "nearestSettlement": {"id": "01a0...", "name": "Anuradhapura", "nameSi": null, "nameTa": null, "settlementType": "city", "basis": "point", "distanceM": 53118.95},
  "nearestRoad": {"id": "01a0...", "name": null, "class": "unknown", "refCode": null, "distanceM": 287.87},
  "insideZones": [],
  "geofenceHits": [
    {"id": "01a0...", "name": "Habarana junction watch zone", "kind": "circle", "tenantId": "wildlife-dept", "version": 1, "relation": "within"}
  ],
  "nearestDevices": [
    {"deviceId": "01a0...", "name": "HB-CAM-01", "deviceType": "camera", "tenantId": "wildlife-dept", "distanceM": 468.41, "inFieldOfView": true}
  ],
  "missingLayers": ["protected_area", "risk_zone"],
  "search": {"settlementRadiusM": 60000.0, "roadRadiusM": 10000.0, "deviceRadiusM": 5000.0, "deviceLimit": 5},
  "refDataRelease": "ref-2026.09-lka-open",
  "computedAt": "2026-09-17T07:26:36.269681Z"
}
```

| Member | Meaning |
|---|---|
| `schema` | Always `geo-context/1` |
| `eventId`, `tenantId`, `observedAt`, `locationSource` | From the request (`observedAt` in UTC) |
| `geometryKind` | `point`, `line` or `area` |
| `admin` | Province, district, DS and GN division containing the event point (lines and areas: a point on the geometry, `ST_PointOnSurface`). A level is `null` where the release has no area. `codes` repeats the codes for attribute rules. `onBoundary` is true when the point lies on a boundary shared by two areas of one level; the lowest code is then reported |
| `nearestSettlement` | Nearest settlement within `search.settlementRadiusM`, else `null`. `basis` `footprint`: distance to the built-up area (0 inside); `point`: distance to the settlement point |
| `nearestRoad` | Nearest road within `search.roadRadiusM`, else `null` |
| `insideZones` | Protected areas (`type` `protected_area`, `category` = designation) and risk zones (`risk_zone`, `category` = risk type, `severity` 1-5) valid at `observedAt` that the event lies in; ordered by type, name, id |
| `geofenceHits` | Active geofences, effective at `observedAt` and visible to the tenant (own, shared with it, or authority-visible), that the event lies in; ordered by name, id. `tenantId` is the owner; `version` the geofence version tested |
| `nearestDevices` | Active devices visible to the tenant within `search.deviceRadiusM`, nearest first, at most `search.deviceLimit`, without the reporting device. `inFieldOfView`: the event intersects the device's field of view at `observedAt`; `null` if the device has none then |
| `missingLayers` | Reference layers the release has no data for. An empty `insideZones` means "not in a zone" only if `protected_area` and `risk_zone` are not listed |
| `search` | Radii (metres, inclusive) and device limit used |
| `refDataRelease` | Release code used (unique; recompute with `refDataRelease=` to reproduce) |
| `computedAt` | When the context was computed (UTC) |

`relation` (zones and geofences): `within` when the whole event geometry lies inside, which is always the
case for a point; `intersects` when a line or area event crosses the boundary.

### Rules and guarantees

* **Distances** are metres on the SLD99 / Sri Lanka Grid 1999 plane (EPSG:5235), rounded to 0.01 m.
  SLD99 grid distances agree with geodesic distances to 250 ppm on the island.
* **Thresholds are inclusive**: with a 500 m radius, features at 499 m and 500 m are included and a
  feature at 501 m is not (tested with positions placed by the database's own transformation).
* **Containment** is evaluated on the WGS84 geometry and includes the boundary: a point on a zone edge,
  on a geofence edge or on the edge of an enclave (hole) is inside.
* **Determinism**: the same event, release and tenant-visible operational data give the same document
  except `computedAt`. Every list has a fixed order; names are compared byte-wise.
* **Consistency**: all parts are computed by one SQL statement, so they come from one snapshot.
* **Idempotency**: `tenantId` + `eventId` + `observedAt` identify an event. Sending it again replaces the
  stored location and context (the document is also stored in `geo.event_geo_context`), including when two
  deliveries of the same event overlap: every write is an upsert and hits the new result no longer has are
  removed.

## Errors

Errors are RFC 9457 problem details (`application/problem+json`). `type` is
`urn:gis-core-service:problem:<code>`; every problem carries `requestId`.

| Status | `code` | When | Extra members |
|---|---|---|---|
| 403 | `forbidden` | `tenantId` is not the tenant the request acts for (`X-GIS-Tenant-Id`, else `GIS_TENANT_ID`) | `tenantId` |
| 403 | `tenant_not_registered` | The tenant is not registered in the GIS service | |
| 404 | `device_not_found` | `deviceId` does not exist for this tenant | `deviceId` |
| 404 | `field_of_view_not_found` | `fieldOfViewId` is not a view of the device at `observedAt` | `fieldOfViewId` |
| 404 | `release_not_found` | `refDataRelease` does not exist | `refDataRelease` |
| 413 | `payload_too_large` | Body larger than `GIS_MAX_REQUEST_BODY_BYTES` (1 MiB) | `maxBytes` |
| 422 | `request_validation_error` | Schema violations: missing or malformed members, unknown members, unsupported geometry types (such as `GeometryCollection`) | `errors` (`loc`, `msg`, `type`) |
| 422 | `invalid_coordinate` | A position is not finite, outside WGS84 or outside the service area | `path`, `position`, `serviceAreaBbox`, `likelySwapped` when `[lat, lon]` was sent |
| 422 | `invalid_geometry` | Too few positions, unclosed ring, self-intersection and other OGC invalidity | `reason` (with location), `path` |
| 422 | `validation_error` | `observedAt` more than 1 day ahead or older than 13 months without a prepared month; a device of another tenant | `observedAt`, `maxClockSkewS`, `deviceId` |
| 422 | `release_not_usable` | `refDataRelease` is a draft | `refDataRelease`, `releaseStatus` |
| 503 | `reference_data_unavailable` | No current release is configured | |
| 503 | `event_partition_missing` | Event storage for the month could not be prepared | `observedAt` |

Nothing is stored when a request fails.

```json
{
  "type": "urn:gis-core-service:problem:invalid_coordinate",
  "title": "Coordinate is not acceptable",
  "status": 422,
  "detail": "geometry is outside the service area but would be inside it with the axes swapped; GeoJSON positions must be [longitude, latitude]",
  "instance": "/geo/v1/enrich",
  "requestId": "5f0c6f0f2f5c4b1f9a55c6f1d2a7e3b4",
  "path": "coordinates",
  "position": [8.0305, 80.7505],
  "serviceAreaBbox": [79.44, 5.66, 82.15, 10.08],
  "likelySwapped": true
}
```

## The tenant

The GIS checks no credentials: the main platform calls it on its internal network and owns sign-in
([../security.md](../security.md)). The request acts for the tenant in `X-GIS-Tenant-Id`, else for the
platform's organisation (`GIS_TENANT_ID`); the event's `tenantId` must be that tenant. The service sets it
for row-level security, so geofences and devices of other tenants stay invisible unless they are shared.

Every call is recorded in the audit log (`events.enrich`, with the event id, the counts of geofence hits
and nearby devices, and a 0.001° extent of the location), in the transaction that stores the event
([../security.md](../security.md#5-audit)).

```bash
curl -s http://localhost:8100/geo/v1/enrich -H "Content-Type: application/json"   -d '{"eventId":"evt-1","tenantId":"dialog-smart-alerts","observedAt":"2026-09-14T08:32:10+05:30",
       "eventType":"wildlife.elephant_detected","sourceType":"sensor","locationSource":"sensor",
       "location":{"type":"Point","coordinates":[80.749,8.037]}}'
```

The tenant must be registered: the `migrate` service registers `GIS_TENANT_ID`; others with
`python -m app.tools.register_tenant --tenant <id> --name <name>`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GIS_ENRICHMENT_SETTLEMENT_RADIUS_M` | 25000 | Search radius for the nearest settlement (max 100 km); also used by `GET /geo/v1/reverse` |
| `GIS_ENRICHMENT_ROAD_RADIUS_M` | 10000 | Search radius for the nearest road; also used by `GET /geo/v1/reverse` |
| `GIS_ENRICHMENT_DEVICE_RADIUS_M` | 5000 | Search radius for nearby devices |
| `GIS_ENRICHMENT_DEVICE_LIMIT` | 5 | Nearby devices returned (0-50; 0 turns the lookup off) |
| `GIS_MAX_REQUEST_BODY_BYTES` | 1048576 | Largest accepted request body |

## Performance

Each enrichment runs a fixed number of statements in one transaction, whatever the number of hits: set
the tenant, look up the device (device events only), store the location, compute the context, store the
context with its hits. The lookup statement uses the GiST indexes on every spatial layer: nearest
searches are index-ordered (KNN) and bounded by the search radius; zone and admin lookups use the
subdivided polygons. Tests check the plans on 20 000 settlements, 10 000 roads, 2 000 zones, 20 000
devices and 10 000 geofences, and compare the answers with a brute-force computation.

Measured on a development machine (PostgreSQL 18.6 + PostGIS 3.6.4 on the same host) with that data:
about 6 ms per enrichment at the median and 8 ms at the 95th percentile, including storage.

Row-level security lets PostgreSQL use an index only through LEAKPROOF operators. The database
initialisation marks the PostGIS `&&` operator as leakproof (`db/admin/postgis-leakproof.sql`); the
readiness check `tenant_spatial_indexes` warns if it is missing, for example after
`ALTER EXTENSION postgis UPDATE`.

## Asynchronous processing (later)

`app.services.enrichment.GeoContextService.enrich(event)` does not depend on HTTP. An event-stream
consumer (plan: NATS `events.ingested` -> `events.geo_enriched`) validates the message into the same
`EventLocationIn` model, authorises the tenant from its stream configuration, calls `enrich`, and
publishes the returned document. Redelivered messages are harmless because enrichment is idempotent.
