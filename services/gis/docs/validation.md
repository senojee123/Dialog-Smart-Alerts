# MVP validation report

Date: 2026-09-25, revised 2026-09-28 after an independent review. Version: 0.1.0 (migration head `20260924_0008`). Candidate: the repository as a GIS
Core Service MVP.

**Verdict: the MVP is functionally complete for its GIS scope and passes every test and acceptance
check in a development environment. It is not production-ready.** What stands between it and production
is listed under [Not yet validated](#not-yet-validated-and-why-this-is-not-production-ready).

## Environment

PostgreSQL 18.6 + PostGIS 3.6.4 (native), Python 3.13.7, Node 22.22, Chromium 141 (headless,
software WebGL), the development sample `ref-2026.09-dev` (37 235 reference features) and the sample
tenant. Docker was not available in the validation environment: the Compose file was validated with
`docker compose config`, and the same steps (init script, migrations, sample loading, API, web client)
were run natively.

An independent code review against the hard constraints (GIS-only boundary, parameterized SQL, no
secrets, tenant from the verified token, development tools refusing production) found no violation.
(Version 1; version 2 removed authentication, ADR-0019: the tenant now comes from the platform.) It
found three defects in the geofence editor and several smaller ones; all are fixed, each with a test that
fails without the fix (section 5).

## 1. End-to-end scenario

| Step | Result | Evidence |
|---|---|---|
| 1. A spatial event is submitted | Pass | `POST /geo/v1/enrich`, pipeline token, `200` |
| 2. Location is validated | Pass | swapped axes: `422 invalid_coordinate` with `likelySwapped`; bow-tie polygon: `422 invalid_geometry` with the reason; nothing stored |
| 3. Geo-context enrichment executes | Pass | `geo-context/1` document, release named |
| 4. Administrative context | Pass | province, district, DS division (codes and names) |
| 5. Nearby settlement | Pass | nearest settlement and distance |
| 6. Nearby road | Pass | nearest road and distance |
| 7. Zone intersections | Pass | sanctuary + two overlapping risk zones, `within` |
| 8. Geofence hits | Pass | the scenario's geofence, at its version |
| 9. Persisted and returned | Pass | stored document identical to the response |
| 10. Event on the MapLibre map | Pass | Chromium: the event (with an id and type of the run) is drawn at its position, selected by a click, the popup shows province, nearest settlement and road and the release; no uncaught page error |
| 11. Spatial queries retrieve it | Pass | events by viewport, geofence hit and administrative area; containment, within-distance and nearest at its position |
| 12. Geofence management | Pass | API: create, read, replace with version (409 on stale), archive, other tenants see nothing; browser: a circle drawn with the editor is stored with its centre and radius and hit by a new event; after a basemap switch a polygon is drawn, a corner dragged, the polygon deselected, and it is stored as edited and hit by a new event |

Automated as `backend/tests/integration/test_end_to_end.py` and `frontend/e2e/map.e2e.ts`
([testing.md](testing.md#the-mvp-scenario-end-to-end)).

## 2. Architecture boundary

No alert service, alert orchestration, notification service, recipient lookup, notification-location
storage, SMS/push/e-mail delivery or alert-specific logic exists. The repository-wide search found 200
matches of the terms in 39 files, all ARIA `role="alert"` error messages, tests asserting absence, or
documentation of the exclusion; none needed removal ([boundary-audit.md](boundary-audit.md)). The
boundary is enforced by tests on the schema, the OpenAPI document, the backend identifiers (including
names of delivery mechanisms such as `send_email`, `smtp`, `webhook`, `fcm`), imports of message
delivery libraries (`smtplib`, `email`, `twilio`, ...), declared dependencies, and the map client's
source.

## 3. Tests

| Suite | Result |
|---|---|
| Backend unit | 655 passed |
| Backend pipeline (GDAL) | 35 passed |
| Backend integration and API (PostGIS) | 509 passed |
| Frontend (Vitest, jsdom) | 315 passed (38 files) |
| Browser end to end (Playwright, Chromium) | 3 passed |
| ruff, ruff format, mypy (strict), tsc, eslint, schema documentation check, production build | clean |

Every required category and boundary case (499/500/501 m, on a boundary, invalid polygons, swapped
coordinates, empty results, overlapping zones) is covered; the mapping is in [testing.md](testing.md).

## 4. Performance

Single client, sequential, dev sample, 2 vCPU ([performance.md](performance.md)):

| Operation | p50 | p95 |
|---|---|---|
| Geo-enrichment (`POST /geo/v1/enrich`, over HTTP) | 9.7 ms | 12.6 ms |
| Spatial queries (features, within-distance, nearest, reverse, events) | 5.4-7.6 ms | 6.3-9.2 ms |
| Containment of administrative areas (returns full polygons) | 10.7 ms | 11.7 ms |
| Events by viewport at 200 000 events a day | 11.6 ms | 14.4 ms |

All large-table accesses use spatial or key indexes. No index was added: none was justified by a plan;
the one slow case (event viewports at volume without the LEAKPROOF setting, 44 ms) is handled by the
setting the deployment already applies.

## 5. Defects found by this validation, and fixed

| Defect | Found by | Fix |
|---|---|---|
| A circle drawn in the geofence editor lost its shape: removing the drawn ring (the circle is stored as centre and radius) was reported by Terra Draw as a deletion, which cleared the draft | browser E2E | the editor ignores deletions of shapes it no longer holds; unit test reproduces the deletion |
| The click that finished a drawing also selected the feature under it and opened its popup | browser E2E | clicks within 400 ms of a finished drawing are not selections; component test |
| The circle hint said "press and drag"; Terra Draw draws a circle with two clicks | browser E2E | hint corrected |
| Reference layers (admin areas, protected areas, risk zones, water, settlements) were not drawn in a real browser: the style layers were wrapped in React fragments inside `<Source>`, which do not receive the source id | browser check | keyed arrays; the map mock now passes the source as react-map-gl does, and a test checks every style layer has its source |
| The attribution control did not update when the catalogue arrived | browser check | control re-created on change |
| File QA read a missing identifier as the text `nan` | pipeline test | missing identifiers counted as missing |
| Deselecting an edited polygon or corridor (a click on the empty map, Escape) emptied the draft: Terra Draw deletes the corner handles it added, and every deletion was taken as the shape's. An unfinished drawing discarded with Escape stayed in the draft | independent review, reproduced in Chromium | changes are reported per feature and the editor only takes those of the shape it holds; component tests and a browser test that drags a corner and deselects |
| Opening a polygon or corridor geofence emptied its geometry when the editor's effect ran again (always in the development build's strict mode): clearing Terra Draw reported the loaded shape's deletion | independent review | the editor lets go of its shape before clearing, and gives Terra Draw the draft as it stands; strict-mode test |
| After a basemap switch, drawing failed and the editor crashed: the new map style removed Terra Draw's sources and the adapter does not restore them | independent review, reproduced in Chromium | Terra Draw is started again on the new style and the editor reloads its draft; hook tests and the browser test switch the basemap first |
| Finishing a draw-to-filter area cleared the geofence being edited | independent review | only the filter's own shape is removed; component test |
| A geofence opened for editing could arrive after the operator had closed the editor or started a new one, and saving would then replace it | independent review | answers to superseded requests are ignored; component test |
| Archived geofences were drawn on the map (dashed, not in the legend) | browser test screenshot | archived geofences are not drawn; component test |
| Choosing *No basemap* said that no basemap was configured | browser test screenshot | the notice depends on the configuration, not the choice; component test |
| The browser test identified the event by a prefix common to every run | independent review | an id and event type of the run; nearest settlement and road asserted; every browser test also asserts that the page raised no uncaught error |
| The seed read existing sites and geofences from one page of 1 000 | independent review | pages through all of them |
| The benchmark relied on `GIS_ENV` alone, which describes the local process and not an API measured over HTTP | independent review | it refuses unless the service's current release is a development or test release; row counts are reported only when measured in process |

## Not yet validated, and why this is not production-ready

| Area | State |
|---|---|
| Containers | Compose and Dockerfiles validated by configuration only; `docker compose up --build` has not been run to completion here |
| Access | No authentication of its own (ADR-0019): the GIS API must stay on the platform's internal network until the platform's proxy checks sign-in |
| Load | No concurrency or throughput test, no soak test, no pool-saturation test |
| Reference data | Development release from open data (OpenStreetMap is not authoritative; risk zones are placeholders). Official datasets need data agreements and approved licence reviews before a production release can be built |
| Operations | No backup, restore or high-availability procedure; no retention jobs for events and the audit log; no partition maintenance job; monitoring dashboards and paging rules not defined |
| Security review | No external penetration test or threat-model review; TLS and ingress configuration belong to the deployment |
| Map client | Tested in desktop Chromium only; no field-device, offline or accessibility audit |

## Remaining limitations

* Event queries need a time window (at most 31 days) because events are partitioned by month.
* No aggregation (counts per area, heatmaps) and no vector tiles for the heavy reference layers; wide map
  views read the first pages of a layer and say so.
* `GET` of one stored geo-context and recompute exist in the service, not over HTTP.
* Basemap labels in Latin script only; Sinhala and Tamil names are in the data but not drawn.
* The basemap (22 MB) is not in git; it is delivered with the working copy or rebuilt from OpenStreetMap.
* The geofence editor and draw-to-filter share one Terra Draw instance: arming draw-to-filter while a
  geofence is being edited takes the shape out of select mode (the draft is kept), and opening the editor
  disarms a filter drawing that was armed. Switching the basemap discards a drawing in progress.
* No event-stream consumer: events arrive over HTTP (`POST /geo/v1/enrich`).

## Deferred features

Event-stream ingestion (NATS), response units (S-05), vector tiles for the reference layers,
aggregation endpoints, saved map views, offline map support, the OGC gateway (only on external demand),
official agency datasets under agreement, retention and partition maintenance jobs, and sign-in checked
in the platform's proxy. Alerting and notification are not deferred: they are outside the
GIS service's scope (ADR-0012).
