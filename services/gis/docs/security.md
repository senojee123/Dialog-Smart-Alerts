# Security and multi-tenancy

How the GIS Core Service decides whose data a request sees, and what it records about it. The GIS runs as
an instance of the main platform (Dialog Smart Alerts), which owns users and sign-in; the decision and its
consequences are in [ADR-0019](adr/ADR-0019-platform-instance-without-own-authentication.md). Tenant
isolation and the audit log come from [ADR-0017](adr/ADR-0017-security-and-multi-tenancy.md).

Principles:

* **No credentials of its own.** The GIS verifies no token and has no roles. It is reached only through the
  main platform, on the platform's internal network.
* **One tenant per request.** A request acts for the tenant in its `X-GIS-Tenant-Id` header, else for the
  platform's organisation (`GIS_TENANT_ID`). PostgreSQL row-level security keeps each tenant's data apart,
  so an application bug cannot mix organisations.
* **Searches, reads of operational data, exports and changes are audited** in an append-only log, in the
  same transaction as the operation. Who and when is stamped by the database.
* **No personal notification data.** The service keeps no recipient, subscriber or contact data and no
  person's location; the audit log keeps coarse extents only.

---

## 1. Access

Nothing asks for credentials: there is no `Authorization` header to send and no endpoint answers 401.
Every request is the caller `platform` with every permission within its tenant
(`app.core.access.PLATFORM_PERMISSIONS`). Acting for all tenants is not among them.

**Where the GIS may be reachable.** Because it checks no credentials, the GIS API must be reachable only
from the main platform's backend (which proxies the map's `/api/gis/*` calls) and its event processing.
Do not expose port 8000 of the API container, `/docs`, `/openapi.json` or `/metrics` to browsers or the
internet. On Railway: no public domain for the GIS API service; the platform reaches it on the private
network.

**When the platform adds sign-in.** Check it in the platform's proxy, and pass the user's organisation on
in `X-GIS-Tenant-Id`. If the GIS should then refuse some operations to some users, `get_principal`
(`backend/app/api/deps.py`) is the one place to build a caller with fewer permissions: every endpoint
already names the permission it needs (`x-gis-permissions` in the OpenAPI document).

**Production guards** (`GIS_ENV=production`): TLS to the database unless
`GIS_DB_ALLOW_INSECURE_TRANSPORT=true` (a private network), separate runtime and migration logins, no
wildcard CORS. The service logs a warning at start-up whenever it runs without them.

## 2. Permissions

Endpoints still check permissions, all of which a request has. They describe what each operation does and
keep a seam for access control; they no longer come from roles or scopes.

| Permission | Operations |
|---|---|
| `map:read` | layer catalogue, map features, reverse geocoding, releases, geofence/site/placement reads |
| `query:spatial` | within-distance, nearest, contains |
| `events:read` | event locations |
| `events:enrich` | `POST /geo/v1/enrich` |
| `geofences:write`, `assets:write` | create, change, archive geofences; sites and device placements |
| `data:purge` | `purge=true` deletes |
| `data:export` | exports |
| `audit:read` | the audit log |

---

## 3. Tenant isolation

**Which tenant a request acts for.** The one in `X-GIS-Tenant-Id`, else `GIS_TENANT_ID`:

* requests need not name it again; `tenantId` in a query, if given, must be that tenant - another one is
  `403` with `tenantId`, and it is never used to read anything;
* a tenant in a request body (the event's `tenantId` for enrichment) must be that tenant as well; objects
  cannot name a tenant at all (unknown members are refused); other tenant headers (`X-Tenant-Id`) are
  ignored;
* a tenant that is not registered is `403 tenant_not_registered`.

**Row-level security.** Every table of tenant data - `ops.site`, `ops.device`, `ops.device_field_of_view`,
`ops.geofence`, `geo.event_location`, `geo.event_geo_context`, `geo.event_geofence_hit`,
`geo.event_zone_hit`, `audit.entry` - has `tenant_id` and row-level security. Policies compare it with
`meta.current_tenant_id()`: a tenant writes only its own rows and reads its own and what was shared with it
(Section 4); without a tenant nothing is visible. Composite foreign keys on `(id, tenant_id)` prevent
cross-tenant links. The runtime login owns no table and cannot bypass row-level security (tested).

**Transaction-scoped context.** Services open every transaction with
`set_config('gis.tenant_id', …, true)` - `SET LOCAL` - together with the caller's subject, client,
request id and cross-tenant flag for the audit log (`app.db.session.access_transaction`). The values end with
the transaction, so a pooled connection never carries one request's tenant into the next (tested, including
after a rollback).

**What another tenant sees.** A private object of another tenant is not visible: reads answer `404`. An
object shared for reading cannot be changed: `403 not_owner`. Cursors are bound to the tenant that
produced them, so a cursor of tenant B is `422 invalid_cursor` for tenant A.

---

## 4. Sharing

Geofences and the operational layers (sites, devices) carry a sharing policy:

| Policy | Who can read the object |
|---|---|
| `private` (default) | The owning tenant only |
| `shared` | The owner, the tenants in `sharedWithTenants`, and authority tenants |
| `authority_only` | The owner and authority tenants (`meta.tenant.kind = 'authority'`) |

A field of view is visible exactly when its device is. Events and geo-context are never shared. Only the
owning tenant can change an object or its sharing policy, and a change of sharing is recorded in the audit
log (`sharingPolicy`, `previousSharingPolicy`, `sharedWithTenants`).

---

## 5. Audit

`audit.entry` (migration 0007) records:

| Category | Operations | Recorded by |
|---|---|---|
| `search` | `query.within_distance`, `query.nearest`, `query.contains`, `query.reverse_geocode`, `features.list` with `nameContains` on reference data | the API, in the answering transaction |
| `sensitive_query` | every read of tenant data: `features.list` on `ops.*`, `events.list`, `geofences.list`, `geofence.read`, `sites.list`, `site.read`, `device_placement.read`; `events.enrich` (the answer names the tenant's geofences and nearby devices); and `audit.list` | the API, in the answering transaction |
| `export` | `export.features`, `export.events` | the API, in the answering transaction |
| `change` | `geofence.create`, `.update`, `.archive`, `.purge`; the same for `site` (`.decommission`) and `device` | triggers on `ops.geofence`, `ops.site`, `ops.device` |
| `release` | `reference_release.create`, `.publish`, `.make_current`, `.unset_current`, `.retire`, `.delete` | a trigger on `meta.ref_data_release` |

Reading reference data by viewport alone is not recorded: it is the same public data for everyone and a map
reads it on every pan.

Each entry holds:

| Field | Content |
|---|---|
| `occurredAt` | Clock time |
| `tenantId` | The transaction's tenant; for a change made directly in the database without one, the changed row's tenant (so the owner sees it); empty for reference data releases |
| `actor` | `subject` (`platform` for API requests) and `clientId` of the caller - the database login when a change was made directly in the database |
| `crossTenant` | The caller acted for a tenant not its own (no API request does) |
| `channel`, `requestId`, `dbUser` | `api`, `loader` or `database`; the request id (also in the access log); the database login |
| `operation`, `category`, `target`, `objectId` | What was done, to which layer or table and object |
| `parameters` | Filters, distances, windows, paging; for changes the version, status and sharing before and after, whether the geometry changed, the geofence kind, radius and area; for releases the code, status, datasets and rejected features |
| `geometryType`, `geometryExtent` | The geometry's type and its bounding box widened to a 0.001° grid (about 110 m) |
| `resultCount` | Features returned or exported; features published with a release |

Guarantees:

* **Fail closed.** API entries are written in the transaction that produces the answer; if the entry
  cannot be written, the request fails and nothing is returned (tested by revoking the insert privilege).
* **No path around it for changes.** Triggers record geofence, site and device changes and release
  lifecycle events whoever makes them - the API, the reference data loader (`--actor`, channel `loader`),
  or a login changing rows by hand (channel `database`).
* **Stamped by the database.** A trigger sets time, tenant, actor, client, request id and channel
  from the transaction context, whatever an INSERT supplies.
* **Append-only.** The runtime login has INSERT and SELECT only; triggers refuse UPDATE, DELETE and TRUNCATE
  for every login. Retention is an administrative act: as the owner, `ALTER TABLE audit.entry DISABLE
  TRIGGER a20_refuse_change`, delete what is past retention, re-enable it - deliberately visible.
* **Isolated.** Row-level security: a tenant reads only its own entries; entries without a tenant are
  visible only to a transaction without one (the loader, a database administrator).

Reading: `GET /geo/v1/audit/entries` (`audit:read`) with `category`, `operation`, `actorSubject`, `from`,
`to`, keyset paging, newest first. Organisation Admins read their tenant's log; a Platform Admin reads a
tenant's log by naming it, and the platform entries (releases) by naming none. Reading the log is itself
recorded.

---

## 6. Privacy

* **No personal notification locations, no recipient tracking.** There is no table, column or endpoint for
  recipients, subscribers, contacts or a person's location, and the service boundary (ADR-0012) keeps it so.
  `tests/integration/test_privacy.py` fails if a migration adds a column named like one, or a geometry
  column in a table that has not been reviewed.
* **No user identities.** `created_by`, `updated_by` and the audit actor hold `platform` (or a database
  login, or a loader's operator), never a person's name or e-mail address (tested). Who in the platform did
  something is the platform's record.
* **Coarse locations in the log.** The audit log keeps a 0.001° cell around a searched geometry, not the
  geometry: a "what is near me" search from a field officer's position must not become a track of that
  officer. The exact position is not stored anywhere (tested). No hash of it is stored either: a point's
  hash could be reversed by trying every position in the cell.
* **Logs.** Access logs record the path, not the query string, so `lon`/`lat` of a reverse geocoding
  request do not reach them; database errors are logged without their bound parameters
  (`hide_parameters`), so a failed search does not write its position into the error log.
* **Shared objects** show a reading tenant where the object is and what it is, not who in the owning
  organisation created or changed it (`createdBy` and `updatedBy` are empty for non-owners).
* **Event locations** are where a device or sensor observed something; the service does not store where
  people are.

---

## 7. How it is tested

| Suite | Proves |
|---|---|
| `tests/integration/test_tenant_isolation.py` | Tenant A cannot retrieve tenant B's operational data: in the database (every tenant table, catalogue-driven; reads, updates, deletes, inserts for B; no tenant; context ends with the transaction) and through the API (map features, spatial questions, exports, geofences, sites, device placements, events, geo-context, audit log; `tenantId` of another tenant, other tenant headers, tenant in a body, cursors). Every check has a control that B's data is there. A new tenant endpoint must be added (coverage test) |
| `tests/integration/test_audit_log.py` | Every search, read of tenant data and export is recorded with actor, tenant, request id, parameters and count; geofence life cycle and release publication are recorded; direct database changes too; stamping cannot be forged; append-only for every login; tenant-isolated; fail-closed; coarse location only |
| `tests/integration/test_privacy.py` | No personal or contact data in the schema or API; identity columns hold subject ids; only reviewed tables hold geometry; the audit grid |
| `tests/unit/test_access.py`, `tests/unit/test_caller.py`, `tests/unit/test_app.py`, `tests/unit/test_config.py` | The platform's permissions; the caller and its tenant; no credentials asked for, the tenant header validated; `GIS_TENANT_ID`; production guards; database errors without parameters |

The isolation suite was checked against two deliberate defects - trusting a client-supplied `tenantId`, and
a row-level security policy that lets every tenant read geofences - and fails on both. An independent
review of the change found no path across tenants; its findings (unaudited enrichment, parameters in error logs, direct changes filed without a tenant, editor ids on shared
objects) are fixed and tested.

---

## 8. Limits

* No authentication: anyone who can reach the GIS API can read and change GIS data. It must stay on the
  platform's internal network (Section 1) until the platform's proxy checks sign-in.
* The audit log is protected by privileges and triggers, not by a hash chain; a database owner can still
  disable the triggers (deliberately, and visibly in the catalogue).
* No automatic retention job for the audit log yet; volume grows with map use of operational layers and
  with the event rate (one entry per enrichment).
* Device ids are chosen by clients (UUIDs). Registering a device under an id another tenant already uses
  answers `409 identifier_in_use`, which tells the caller the id exists - not whose it is or where; with
  random UUIDs this cannot be used to enumerate devices.
