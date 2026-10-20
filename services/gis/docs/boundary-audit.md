# GIS-only boundary audit

Date: 2026-09-25, repeated 2026-09-28 after the validation's fixes. Scope: every file of the repository
except third-party code (`frontend/node_modules`), build output, caches, dependency lock hashes, raw
source data and this report. Terms searched, case-insensitive: `alert`, `recipient`, `notification`,
`notify`, `notification_location`; every match is counted (`rg -i -o`). The built reference data
(`data/sample/ref-2026.09-dev/*.geojson.gz`, decompressed), the fixtures and the declared dependencies
were searched as well.

**Result: 200 matches in 39 files, none of which violates the boundary.** Nothing was removed, because
nothing implements alerting: there is no alert service, alert orchestration, notification service,
recipient lookup, notification-location storage, SMS/push/e-mail delivery or alert-specific business
logic, and no messaging dependency. The reference data and fixtures contain none of the terms. (The first
run of this audit counted matching lines, 100 in 36 files; the rise since is the guards and documentation
added by the validation, not new functionality.)

Categories: **1** unrelated technical terminology (including tests that assert the *absence* of
alerting); **2** documentation of the exclusion or of an external consumer; **3** code that violates the
boundary.

| File | Matches | Category | What the occurrences are |
|---|---|---|---|
| `frontend/src/map/**/*.tsx` (MapContainer, SpatialTools, FeaturePopup, EventFilters, ExportPanel, GeofenceEditor) | 6 | 1 | `role="alert"`: the WAI-ARIA live-region role that makes screen readers announce an error message in the UI |
| `frontend/src/map/**/*.test.tsx` (6 files) | 9 | 1 | `getByRole('alert')`: tests finding those error messages |
| `frontend/src/map/boundary.test.ts` | 14 | 1 | The client's boundary guard: fails if its source speaks of notifications, recipients or channels, or calls a path about them |
| `backend/tests/unit/test_spatial_model_contracts.py` | 5 | 1 | Guards: no alerting tables modelled; `recipients` is refused as an unknown input member |
| `backend/tests/unit/test_app.py` | 4 | 1 | Guard: no API member named after recipients or alerts |
| `backend/tests/integration/test_spatial_model.py` | 9 | 1 | Guard: no table or column matching alert, notification, recipient, subscriber, phone, e-mail |
| `backend/tests/integration/test_privacy.py` | 7 | 1 | Guard: nothing in the schema is about people as recipients or contacts |
| `backend/tests/integration/test_spatial_query_api.py` | 6 | 1 | Guard: the OpenAPI document offers no notify, notification, recipient, alert, subscriber or SMS surface |
| `backend/tests/integration/test_reference_loader.py` | 1 | 1 | A manifest naming the layer `ref.notification_location` is refused: the layer does not exist |
| `backend/tests/unit/test_service_boundary.py` | 15 | 1 | Guard added by this audit: no Python identifier, file name, import or dependency about alerts, notifications, recipients or message delivery (238 checks), and a check that the patterns recognise what they forbid |
| `backend/app/__init__.py`, `app/main.py`, `app/api/v1/enrichment.py`, `app/services/enrichment/service.py`, `app/services/spatial_query.py`, `app/schemas/geo_context.py`, `app/schemas/spatial_query.py` | 12 | 2 | Docstrings and the OpenAPI description stating that the service produces spatial facts only and does not raise alerts or select recipients |
| `db/migrations/versions/20260915_0005_event_geometry.py` | 2 | 2 | Docstring: nothing in the event schema selects recipients or sends notifications |
| `README.md` | 13 | 2 | The boundary statement, the guides table and the list of boundary tests |
| `ARCHITECTURE.md` | 41 | 2 | Section 2.2 *Alert Service exclusion*: the plan items removed (S-08 recipient lookup, the notification-locations layer, alert text), and how an external service may use the generic spatial APIs |
| `docs/adr/ADR-0012-gis-only-service-boundary.md` | 16 | 2 | The decision that excludes the Alert Service |
| `docs/adr/ADR-0015-spatial-query-api.md`, `ADR-0016-map-client.md` | 11 | 2 | Why the query API and the map client have no recipient or notification surface |
| `docs/api/README.md`, `docs/api/enrichment.md`, `docs/frontend/map-client.md`, `docs/database/README.md`, `docs/security.md` | 20 | 2 | Statements of the exclusion (no alert endpoint or fields, no notification UI, no recipient tables, no personal notification data) |
| `docs/validation.md` | 9 | 2 | The validation's boundary result and the statement that alerting is out of scope, not deferred |

## How the boundary is kept

| Layer | Check |
|---|---|
| Database | `test_no_alerting_or_notification_objects_exist`, `test_privacy.py` (every table, column and geometry column against a reviewed list) |
| API | `test_the_api_offers_no_recipient_or_notification_endpoint` (OpenAPI paths, operations and schemas) |
| Backend code | `tests/unit/test_service_boundary.py` (identifiers, file names, imports, dependencies) |
| Map client | `frontend/src/map/boundary.test.ts` (source text and called paths) |

A service that needs proximity-based notification owns that design and may call the generic spatial
APIs (`within-distance`, `nearest`, `contains`) over GIS-owned layers; see ADR-0012.
