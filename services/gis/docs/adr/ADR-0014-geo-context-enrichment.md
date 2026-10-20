# ADR-0014: Geo-context enrichment engine and its API

* Status: accepted
* Date: 2026-09-17
* Refines: plan §4.2, §5.3, §7 (`POST /geo/v1/enrich`), §9 (authentication); ADR-0012, ADR-0013

## Context

The enrichment engine turns an event location into a `geo-context/1` document and is reached
synchronously over HTTP now, and through an event stream later (NATS, plan Phase 2). Findings while
building it:

* The event names its tenant, but the architecture (ADR-09, ARCHITECTURE.md 6.4) forbids taking a tenant
  from a client. The plan specifies Keycloak OIDC with JWT checks.
* Six lookups (admin areas, settlement, road, zones, geofences, devices) issued one by one cost six round
  trips and can each see a different snapshot of the data under READ COMMITTED.
* On tenant tables (row-level security) PostgreSQL used no spatial index at all: a query condition can
  become an index condition there only if its operator is LEAKPROOF, and PostGIS 3.6 does not mark its
  geometry operators (`&&`, `<->`, `@`, `~`) leakproof. Geofence lookups were sequential scans
  (verified with EXPLAIN).
* A check "does the release contain any settlements" written as `EXISTS` over the feature table was
  planned as a sequential scan that stops at the first match, whose cost depends on the physical row
  order.
* The document stored by the data model used `schemaVersion`, `zones` and `referenceDataRelease`; plan
  §5.3 and the enrichment specification name them `schema`, `insideZones` and `refDataRelease`.

## Decision

1. **Tenant from the event, authorised by the token.** `POST /geo/v1/enrich` requires a bearer JWT
   verified against the identity provider's JWKS (issuer, audience, expiry; asymmetric algorithms only)
   and the scope `gis:enrich`. The event's `tenantId` is used only if the token's tenant claim lists it,
   or the token has `gis:tenants:all` (platform services such as the event processor). The tenant must be
   registered in `meta.tenant`. Without authentication settings the endpoint answers 503; production
   refuses to start without them. A development tool issues tokens from a local key pair.
2. **One statement per lookup.** Release resolution and all six lookups run as one SQL statement of
   LATERAL subqueries, each index-driven. Per event the service issues a fixed number of statements:
   tenant, device (device events only), location upsert (which also discards a stale context), lookup,
   and one statement that stores the document with its zone and geofence hits.
3. **Explicit bounding-box conditions on tenant tables, and a leakproof `&&`.** The lookup states
   `geom && event` (polygon geofences), `geom_metric && event` (circles, corridors) and
   `geom_metric && ST_Expand(event, radius)` (devices). The database initialisation marks
   `geometry_overlaps` (the `&&` operator) LEAKPROOF; it returns only a boolean and cannot fail for the
   typmod-constrained columns of this schema, so it reveals nothing about rows the policy hides. A
   readiness check warns when the attribute is missing.
4. **Missing layers from lineage.** `missingLayers` lists reference layers without a completed load with
   loaded features in the release (`meta.dataset_load`). Published releases are immutable, so the counts
   are final, and the check reads a few rows.
5. **Document layout of plan §5.3.** Migration `20260917_0006` renames the members to `schema`,
   `insideZones` and `refDataRelease` (the release code, which is unique), adds `tenantId`,
   `admin.codes`, `missingLayers` and `inFieldOfView`, ties `schema`, `eventId`, `tenantId` and
   `refDataRelease` to the row's columns, and converts stored documents in both directions. The schema
   stays `geo-context/1` because the earlier layout was never released.
6. **Deterministic output.** Every list has a fixed order with id as the last key; names and codes are
   compared with the `C` collation (byte order, the same as Python's); distances are rounded to 0.01 m;
   `observedAt` is normalised to UTC. The clock is injected, so tests compare whole documents.
7. **Transport-neutral service.** `GeoContextService.enrich(EventLocationIn)` has no HTTP types. The
   HTTP router and a future stream consumer only authorise the tenant, call it and return or publish the
   document. The event key (tenant, event id, observation time) makes redelivery harmless: location,
   context and hits are written as upserts, and hits the new result no longer has are deleted in the same
   statement, so two overlapping deliveries of one event end with one consistent result instead of a
   unique-violation error.
8. **Nearby devices** exclude the reporting device and say whether the event lies in each device's field
   of view at the observation time.

## Consequences

* The service fetches the identity provider's JWKS (5 s timeout). This is its only outbound call. Keys
  are cached for `GIS_AUTH_JWKS_CACHE_S` (300 s), which bridges short outages; after that, an unreachable
  provider yields 503 until it is back.
* `ALTER EXTENSION postgis UPDATE` can recreate `geometry_overlaps` without the LEAKPROOF attribute; the
  operator runbook re-applies `db/admin/postgis-leakproof.sql` after every PostGIS update, and readiness
  warns if it was missed. Managed databases without a superuser
  cannot apply it: results stay correct, tenant-table lookups become sequential.
* Reference data inserted outside the loader must also record a completed load with its count, or the
  layer is reported missing.
* Tests pin the behaviour: the 499/500/501 m cases around a 500 m threshold (positions found by
  bisection with the database's transformation), boundary inclusion, tenant isolation, missing reference
  data, the number of statements per event, index usage on 20 000-row tables, and a brute-force
  comparison of the answers.
* Consumers of the stored document read the new member names; no released client used the old ones.
