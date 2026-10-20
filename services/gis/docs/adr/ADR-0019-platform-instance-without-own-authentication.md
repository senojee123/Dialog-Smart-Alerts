# ADR-0019: A GIS instance of the main platform, without its own authentication

* Status: accepted
* Date: 2026-10-14
* Supersedes: the authentication and role parts of ADR-0017 (decisions 1-3 and the token checks). Keeps
  its tenant isolation (row-level security) and audit log.

## Context

The GIS Core Service joins the repository of the main platform, Dialog Smart Alerts, as its GIS instance
(`services/gis`). The platform ingests detections, runs the alert rules, notifies stakeholders and owns the
user interface. Users and sign-in are the platform's concern. Today the platform has one organisation and no
user roles.

Version 1 of the GIS verified OIDC bearer tokens (Keycloak), mapped seven GIS roles and six scopes onto
permissions, and took the tenant from the token. Inside the platform that would mean a second identity
system for one application, tokens that expire on every developer machine, and a map that cannot load
until the platform issues tokens of a shape it has no other use for.

## Decision

1. **No credentials.** The GIS verifies no token and has no roles. The token verifier, the JWT dependency,
   the development token tool and its signing keys, the `GIS_AUTH_*` settings and the production check that
   required an identity provider are removed. No endpoint answers 401.
2. **One caller: the platform.** Every request acts as the subject `platform` with every permission within
   its tenant (`app.core.access.PLATFORM_PERMISSIONS`; acting for all tenants is not among them).
   Endpoints still name the permission they exercise (`Principal.require`, `x-gis-permissions`), so
   access control can return in one place, `app.api.deps.get_principal`, if the platform ever needs it.
3. **The tenant comes from the platform.** A request acts for the tenant in its `X-GIS-Tenant-Id` header,
   else for `GIS_TENANT_ID` (default `dialog-smart-alerts`). `tenantId` in a query or body must name that
   tenant (otherwise 403). The `migrate` service registers `GIS_TENANT_ID`
   (`python -m app.tools.register_tenant`).
4. **Tenant isolation and the audit log stay.** Row-level security, the per-tenant audit log and its
   append-only rules are unchanged. They keep organisations apart when the platform has more than one,
   and they cost nothing while it has one. The audit log records `platform` as the actor and no roles.
5. **The GIS is reached only through the platform.** The platform's backend proxies `/api/gis/*` to the
   GIS API, which is not exposed to browsers or the internet. Its port, `/docs` and `/metrics` stay on
   the internal network.

## Consequences

* The map and the platform's event processing work without tokens; nothing expires.
* Anyone who can reach the GIS API can read and change GIS data. That is acceptable only on a private
  network behind the platform. When the platform adds sign-in, its proxy is where to check it, and the
  header it sets (`X-GIS-Tenant-Id`) is how it passes the user's organisation on.
* The database schema is unchanged; no migration was needed (`audit.entry.actor_roles` stays, empty).
* Version 1, with Keycloak authentication, is kept outside the platform repository as
  `gis-core-service-v1-standalone`.
