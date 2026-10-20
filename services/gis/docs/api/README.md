# API reference

Every endpoint the GIS Core Service implements (29 operations, plus `/metrics`). The machine-readable
contract is the OpenAPI document served at `/openapi.json` (interactive at `/docs`); the pages linked
below explain behaviour, errors and examples.

Conventions for all `/geo/v1` endpoints: no credentials (the GIS is reached only through the main
platform, which owns sign-in); GeoJSON in WGS 84 `[longitude, latitude]`; distances in metres measured in
SLD99 (EPSG:5235), thresholds inclusive; containment boundary-inclusive; errors as RFC 9457 problem
details with a code (`type` = `urn:gis-core-service:problem:<code>`) and the request id; keyset paging
(`limit`, `nextCursor`). A request acts for the tenant in its `X-GIS-Tenant-Id` header, else for the
platform's organisation (`GIS_TENANT_ID`) ([../security.md](../security.md)).

| Method and path | Permission | What it does | Reference |
|---|---|---|---|
| `GET /health/live` | - | Liveness: the process answers | [README](../../README.md#configuration) |
| `GET /health/ready` | - | Readiness: database, PostGIS version, CRS consistency, spatial indexes under RLS, migration head | [README](../../README.md#configuration) |
| `GET /metrics` | - | Prometheus metrics (`GIS_METRICS_ENABLED`) | [README](../../README.md#configuration) |
| `GET /geo/v1/service-area` | - | The accepted area (Sri Lanka and nearshore waters) as a GeoJSON Feature | [spatial-queries.md](spatial-queries.md) |
| `POST /geo/v1/enrich` | `events:enrich` | Validate an event's location, compute its geo-context (admin areas, nearest settlement and road, zones, geofence hits, nearby devices), store both, return it | [enrichment.md](enrichment.md) |
| `GET /geo/v1/layers` | `map:read` | Layer catalogue: geometry, CRS, capabilities, filters, attribution, exportability | [spatial-queries.md](spatial-queries.md#get-geov1layers) |
| `GET /geo/v1/layers/{layer}/features` | `map:read` | Features of a layer by viewport, attributes and instant; paged | [spatial-queries.md](spatial-queries.md#get-geov1layerslayerfeatures) |
| `POST /geo/v1/query/within-distance` | `query:spatial` | Objects of a layer within N metres of a geometry, nearest first | [spatial-queries.md](spatial-queries.md#post-geov1querywithin-distance) |
| `POST /geo/v1/query/nearest` | `query:spatial` | The nearest objects, bounded by a maximum distance | [spatial-queries.md](spatial-queries.md#post-geov1querynearest) |
| `POST /geo/v1/query/contains` | `query:spatial` | Areas that contain (or intersect) a geometry, with the relation | [spatial-queries.md](spatial-queries.md#post-geov1querycontains) |
| `GET /geo/v1/reverse` | `map:read` | Administrative hierarchy, nearest settlement and road of a position | [spatial-queries.md](spatial-queries.md#get-geov1reverse) |
| `GET /geo/v1/events` | `events:read` | Event locations of a tenant in a time window (at most 31 days), by area, type, source, device, geofence hit or administrative area | [spatial-queries.md](spatial-queries.md#get-geov1events) |
| `GET /geo/v1/geofences` | `map:read` | List geofences (own and shared), filtered and paged | [spatial-queries.md](spatial-queries.md#geofences) |
| `POST /geo/v1/geofences` | `geofences:write` | Create a polygon, circle or corridor geofence | [spatial-queries.md](spatial-queries.md#geofences) |
| `GET /geo/v1/geofences/{id}` | `map:read` | Read a geofence | [spatial-queries.md](spatial-queries.md#geofences) |
| `PUT /geo/v1/geofences/{id}` | `geofences:write` | Replace a geofence, based on the version read (409 on conflict) | [spatial-queries.md](spatial-queries.md#geofences) |
| `DELETE /geo/v1/geofences/{id}` | `geofences:write` (`data:purge` with `purge=true`) | Archive, or purge irreversibly | [spatial-queries.md](spatial-queries.md#geofences) |
| `GET /geo/v1/sites` | `map:read` | List installation sites | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `POST /geo/v1/sites` | `assets:write` | Create a site | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `GET /geo/v1/sites/{id}` | `map:read` | Read a site | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `PUT /geo/v1/sites/{id}` | `assets:write` | Replace a site | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `DELETE /geo/v1/sites/{id}` | `assets:write` (`data:purge` with `purge=true`) | Decommission, or purge | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `GET /geo/v1/devices/{id}/placement` | `map:read` | Where a device is and what it observes (field of view) | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `PUT /geo/v1/devices/{id}/placement` | `assets:write` | Register or move a device, with its field of view | [spatial-queries.md](spatial-queries.md#sites-and-device-placements) |
| `GET /geo/v1/layers/{layer}/export` | `data:export` + `map:read` | The whole selection of a layer as one GeoJSON file (refused when the data's licence forbids redistribution) | [spatial-queries.md](spatial-queries.md#exports) |
| `GET /geo/v1/events/export` | `data:export` + `events:read` | The events of a window as one GeoJSON file | [spatial-queries.md](spatial-queries.md#exports) |
| `GET /geo/v1/audit/entries` | `audit:read` | The tenant's audit log | [spatial-queries.md](spatial-queries.md#get-geov1auditentries) |
| `GET /geo/v1/me` | - | The caller's permissions and tenant | [spatial-queries.md](spatial-queries.md#get-geov1me) |
| `GET /geo/v1/releases` | `map:read` | Published reference data releases | [releases.md](releases.md) |
| `GET /geo/v1/releases/{code}` | `map:read` | One release: every dataset's lineage and licence, basemap artifacts, QA | [releases.md](releases.md) |

Every request has every permission listed (ADR-0019); they describe what each operation does and are
the seam for access control should the platform need it ([../security.md](../security.md#2-permissions)).

There is no endpoint for alerts, notifications, recipients or people's locations, and a test keeps it so
([../boundary-audit.md](../boundary-audit.md)).
