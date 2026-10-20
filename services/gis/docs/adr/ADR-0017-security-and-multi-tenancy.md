# ADR-0017: Security and multi-tenancy - roles, tenant from identity, audit

* Status: accepted; authentication and roles superseded by
  [ADR-0019](ADR-0019-platform-instance-without-own-authentication.md) (tenant isolation and audit kept)
* Date: 2026-09-23
* Refines: plan §9 (security, Keycloak, tenant isolation, audit); ADR-09 (tenant context), ADR-0012
  (service boundary), ADR-0015 (query API)

## Context

The service already verified OIDC bearer tokens, authorised operations with four scopes, took the tenant
from the token and enforced it with row-level security. What was missing for the platform:

* People are managed in Keycloak with roles - Platform Admin, Organisation Admin, Control Room Operator,
  Investigator, Field Officer, Technician, Viewer. Scopes describe what an OAuth *client* was granted, not
  what a *person* may do; mapping every role onto client scopes would make the web client carry the union
  of everyone's rights.
* Keycloak tokens have a specific shape: client roles under `resource_access.<client>.roles`, realm roles
  under `realm_access.roles`, a `typ` of `Bearer`, `ID` or `Refresh`, and tenants either as a mapped user
  attribute or as an `organization` claim.
* Searches, reads of operational data, exports, geofence changes and reference data releases must be
  audited, with who, which tenant, what, when, the geometry and filters, and the result count.
* An audit entry that is written after the answer can be lost; one written by application code can be
  forgotten by the next code path; one whose actor the writer supplies can be forged by that writer.
* Some searches are made from where a person stands ("what is near me"). A log of their exact geometry
  would be a log of where people were.
* Development needs tokens without a Keycloak, and nothing about that may reach production.

## Decision

1. **Permissions, not roles, in the code.** Ten permissions (`map:read`, `query:spatial`, `events:read`,
   `geofences:write`, `assets:write`, `data:purge`, `data:export`, `audit:read`, `events:enrich`,
   `tenants:all`) are what endpoints check. One table maps the seven roles onto them and one maps scopes
   onto them (`app/core/access.py`). A token's permissions are its roles' permissions, narrowed by its GIS
   scopes if it has any; a token without roles has its scopes' permissions only if it was issued to a
   named service client (`GIS_AUTH_SERVICE_CLIENTS`, required in production). A scope never widens what a
   person may do, and a person without a role gets nothing from their client's scopes.
2. **Keycloak client roles by default.** Roles are read from `resource_access.<GIS_AUTH_ROLE_CLIENT>`
   (default: the audience); realm roles only when enabled, with an optional prefix. Unknown roles are
   ignored; a malformed role, scope or tenant claim invalidates the token.
3. **Only access tokens.** `typ` must be `Bearer` when present; tokens issued for longer than
   `GIS_AUTH_MAX_TOKEN_LIFETIME_S` are refused; `GIS_AUTH_ALLOWED_CLIENTS` can restrict `azp`.
4. **The tenant comes from the identity**, unchanged in principle from ADR-09 and now carried as an
   `Access` (actor + tenant + cross-tenant flag) through every service method. `tenantId` selects among the
   token's tenants; `tenants:all` may name any tenant and is recorded as cross-tenant access.
5. **Declared and enforced together.** Each operation declares its permissions in OpenAPI
   (`x-gis-permissions`). A test derives every role's expected outcome for every operation from those
   declarations and the role table and calls the real API, so the two cannot drift apart.
6. **One audit table, two writers, one stamp.** `audit.entry` is written by the API for reads (searches,
   sensitive queries, exports) in the same transaction as the answer - fail closed - and by triggers for
   changes (geofences, sites, devices) and reference data releases, so no code path can skip them. A
   BEFORE INSERT trigger stamps time, tenant, actor, client, roles, request id and channel from the
   transaction-local context the service sets with the tenant; the writer cannot choose them.
7. **Append-only, isolated.** INSERT and SELECT for the runtime login; UPDATE, DELETE and TRUNCATE refused by
   triggers for every login; row-level security by tenant. Retention requires disabling the trigger.
8. **Coarse geometry.** The log keeps a geometry's type and its bounding box widened to a 0.001° grid,
   never the geometry and never a hash of it (a point's hash can be reversed within its cell).
9. **What counts as sensitive.** Every read of tenant data (operational layers, geofences, sites, device
   placements, events), every enrichment call (its answer names the tenant's geofences and nearby devices)
   and every export; every spatial question and reverse geocoding as a search; reference data read by
   viewport alone is not recorded.
10. **Development tokens stay in development.** `dev_auth` issues Keycloak-shaped tokens and refuses
    `GIS_ENV=production`; a production service refuses `GIS_AUTH_JWKS_PATH` and non-https issuers; a
    production web build ignores `VITE_API_ACCESS_TOKEN`.
11. **The client offers what the caller may use.** `GET /geo/v1/me` reports roles, permissions and tenants;
    the map shows the editor, events, spatial questions and exports only when permitted. The API checks
    regardless.

## Consequences

* Adding a role is a row in one table plus the Keycloak role; adding an endpoint needs a permission
  declaration, an entry in the role test and in the tenant isolation test (both fail until it is added).
* Every read of an operational layer writes one row. A map that pans across a busy area writes several per
  window; the table is indexed for reading by tenant and time and has a BRIN index for retention.
* An audit failure makes reads fail. That is intended; the database must be monitored accordingly.
* Existing clients using scopes (`gis:read`, `gis:write`, `gis:enrich`, `gis:tenants:all`) keep working; the
  error member for a missing grant is now `requiredPermission` instead of `requiredScope`.
* Keycloak itself was not available in the build environment; the token handling is tested with tokens of
  Keycloak's shape. One end-to-end login against the platform realm remains to be done.
