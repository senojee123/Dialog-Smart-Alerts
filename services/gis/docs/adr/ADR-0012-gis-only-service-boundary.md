# ADR-0012: GIS-only service boundary (Alert Service excluded)

* Status: accepted
* Date: 2026-09-15
* Numbering: continues the plan's ADR-01 to ADR-11

## Context

Plan v0.9 treated an Alert Service as a direct consumer of the GIS service. The service would have
looked up notification recipients near an event (capability S-08), stored users' notification
locations as an operational layer, and produced reverse-geocoded text for alert messages. This
coupled the GIS service to notification policy and to personal location data, neither of which is
spatial intelligence.

## Decision

The GIS Core Service is responsible only for geospatial intelligence:

* Event -> geo-context enrichment -> geo-context.
* Clients, rules, investigation UX and other services -> spatial APIs -> PostGIS.

It does not send alerts, orchestrate notifications, identify recipients, store user notification
locations or integrate notification channels. S-08 and the notification-locations layer are removed.
`GET /geo/v1/reverse` stays, redefined as reverse geocoding for geographic context. Generic spatial
queries (`within-distance`, `nearest`, `contains`) stay, operate only on GIS-owned layers, and use
consumer-neutral names.

## Consequences

* The GIS data model holds no individual people's locations except response-unit positions (for
  "nearest response team"), which are last-known, expiring and access-logged.
* A service that needs proximity-based notification designs it itself and may call the generic spatial
  APIs. Adding a people-location layer to GIS requires a new ADR.
* Plan dependencies, risks and questions tied to alert recipients (§16 W17 dependency, §17 Q6, part of
  R7) no longer apply to this service. See ARCHITECTURE.md Section 2.2 for the full list.
