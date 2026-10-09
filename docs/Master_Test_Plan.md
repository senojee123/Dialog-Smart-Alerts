# Dialog Smart Alerts — Master Test Plan & Test Specification

As of 2026-10-07.

## Document Control

### Revision history

| Version | Date | Author | Description of change |
| --- | --- | --- | --- |
| 0.1 | 2026-10-07 | QA (Claude Code, AI-assisted) | Draft produced from a full read of the backend (FastAPI), frontend (React/Vite) and MQTT ingestion pipeline. |
| 1.0 | 2026-10-07 | QA (Claude Code, AI-assisted) | Issued for execution. |

### Review & approval

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product Owner | | | |
| Head of Engineering | | | |
| QA Lead | | | |
| Test Executor(s) | | | |

## 1. Introduction

### 1.1 Background

Dialog Smart Alerts is a general-purpose notification and alerting platform. Its phase-1 use case is elephant detection on roads in Sri Lanka, but the architecture is deliberately use-case-driven: devices submit detection events, a configurable rule engine decides whether to open an incident and notify stakeholders, and a spatial engine independently drives LED road-sign colour by proximity and time-decay. None of the elephant-specific behaviour is hardcoded — it is seeded data (use cases, zones, rules, stakeholders) that an admin configures through a Setup Wizard.

The platform has no scheduled live deployment at the time of writing, but it has been exercised against a real camera gateway over MQTT, with real SMS dispatch, so correctness here has immediate real-world consequences: a missed detection or a mis-attached photo is not a cosmetic bug, it is a safety-relevant failure for a wildlife-corridor alerting system.

The platform is a single FastAPI backend (serving both the API and the built React dashboard) talking to: a public MQTT broker (`broker.hivemq.com`) for camera/gateway ingestion, an SMS gateway (Ideabiz) for stakeholder notification, and JSON-file storage (`backend/data/*.json`) for all entities. There is no database server — `data_store.py` is a generic flat-file CRUD layer.

### 1.2 Purpose of this document

This document is both a plan (what, why, how, who, when) and a specification (exact steps and expected results for every test). It is designed so a tester unfamiliar with the codebase can execute it and produce evidence suitable for a go/no-go decision before a live pilot or a stakeholder demo.

### 1.3 Objectives

- **Prove the ingestion contract holds**: a detection event — from a real device, the simulator, or the phone-camera upload — reliably produces the correct event → incident → notification → sign-actuation chain, exactly as documented in `docs/integration-contract.md`.
- **Prove the MQTT image-correlation fix holds**: this session fixed a real, already-encountered production bug where camera photos sent as a separate MQTT message were silently lost. Regression coverage for every message ordering (image-before-alert, image-during-ingestion, image-after-alert) is a first-class objective, not an afterthought.
- **Prove notification precedence and de-duplication**: a confirmed rule outranks an immediate rule which outranks a pending-confirmation rule; notifications fire only on open/escalation/cooldown-expiry, never storm.
- **Prove the spatial engine is correct independent of the rule engine**: sign colour is purely a function of detection proximity and elapsed time, and must never be forced by rule logic.
- **Prove incident expiry/archival is lossless**: an incident older than the configured window disappears from the live dashboard but is fully recoverable from the incident log.
- **Prove tenant/device security**: an unregistered or disabled device cannot inject detections; a device's API key is never leaked back to the client.
- **Surface risks early**: record every divergence between code and the documented contract, flagged WATCH and consolidated in Appendix A.

### 1.4 Intended audience

| Reader | How they use this document |
| --- | --- |
| Product Owner | Reads the scope, risks and exit criteria; makes the go/no-go call. |
| QA Lead | Owns the plan, allocates chapters, reviews evidence, triages defects. |
| Tester / intern | Executes a chapter at a time, fills Actual Result and Status per row. |
| Developers (incl. the camera/gateway integration team) | Uses failed cases and WATCH notes to reproduce and fix issues; the integration-contract chapter is their primary reference. |

## 2. Application Under Test

### 2.1 System components

| Component | Technology | Purpose | Primary tests |
| --- | --- | --- | --- |
| Dashboard | React, Vite, Tailwind, react-router | Live Incidents, Incident Log, Road Signs, GIS/Map, Devices, Simulator, Setup Wizard, admin CRUD, Style Guide | ENV, LIV, ADM |
| Backend API | FastAPI, generic JSON-file store (`data_store.py`) | Device registry, ingestion boundary, rule engine, spatial engine, notifications, incident CRUD, SSE stream | ING, RUL, SPA, NOT, SEC |
| MQTT client | `paho-mqtt`, background thread in-process with FastAPI | Subscribes to the gateway's alert/image/status/heartbeat topics on the public `broker.hivemq.com`, authenticates producers, feeds the same ingestion boundary as HTTP | MQT |
| Simulator | `simulator.py` + `/simulator` page | Drives the real ingestion path with synthetic single events or moving-target scenario runs, tagged `source="simulation"` | SIM |
| Kiosk / road-sign displays | Served at `/device/:deviceId`, `/display`, `/screen` style routes | Public, no-login big-screen views of live incident/sign state | LIV |
| Storage | Flat JSON files under `backend/data/` (gitignored, re-seeded on first boot) | All persistent entities: devices, zones, use cases, rules, stakeholders, incidents, incident_log, detection_events, notifications, auth_attempts | DAT |

### 2.2 Ingestion boundary (the contract every producer must honour)

Every detection — real device, phone-camera upload, or simulator — funnels through `_ingest_event(body, source)` in `server.py`. The public entry point is `POST /api/events`, authenticated with the device's `api_key` (`X-API-Key` header or body field), resolving the device by `device_id` or `external_id` (MAC/serial), and de-duplicating by `client_event_id`. The platform does **no inference**: producers (edge cameras, an upstream AI service, or the MQTT gateway) send finished detections with `object_type` and `confidence` already decided. This contract is documented in `docs/integration-contract.md` and is the single source of truth for what a producer is allowed to assume.

### 2.3 User-visible entities and their gates

| Entity | Who creates/decides it | What it gates |
| --- | --- | --- |
| Device | Admin (dashboard → Devices, or `POST /api/devices`) | Issues the `api_key` a producer must present; an unknown or disabled device is rejected at ingestion |
| Rule | Admin (`/admin/rules`) | Decides whether a detection opens/escalates an incident, and which stakeholders + sign state it triggers; precedence: confirmed rule > immediate rule > pending-confirmation rule |
| Incident | Opened automatically by the rule engine; closed/resolved by an operator; auto-**expired** off the dashboard after `ALERT_EXPIRY_S` (3h) into the incident log | Drives notifications, sign state inputs, and the Live Incidents / Incident Log views |
| Road sign | Zone + `propagation_radius_m` config | State (WARNING/CAUTION/CLEAR) is computed purely by the spatial engine from event proximity + time-decay — never forced by the rule engine |
| Stakeholder | Admin (`/admin/stakeholders`) | Receives SMS/WhatsApp notifications per rule `notify_stakeholder_ids`, subject to the cooldown |

### 2.4 Notification precedence & cooldown (the core correctness guarantee)

A detection is matched against rules in priority order. If a confirmed (dual-detection) rule and an immediate (single-detection) rule both exist for the same zone/object, the confirmed rule's escalation must never be blocked by the immediate rule already having opened the incident — escalation always wins. Notifications fire only on: first open, a severity escalation, or after `NOTIFY_COOLDOWN_S` (10 min) has elapsed since the last notification on that incident — a sustained presence (detections every few seconds) must never fan out repeat alerts.

## 3. Test Scope

### 3.1 In scope

| # | Area | Included |
| --- | --- | --- |
| 1 | Device registration & auth | Create device, API-key issue/regenerate, resolution by `device_id`/`external_id`, disabled-device rejection, grace-period auth |
| 2 | HTTP ingestion | `POST /api/events` full contract: required fields, idempotency via `client_event_id`, location inheritance, legacy `/api/upload` |
| 3 | MQTT ingestion | Alert JSON parsing, raw-image topic, image/alert correlation (all three orderings), liveness/status/heartbeat, auth grace period |
| 4 | Rule engine | Immediate vs confirmed vs pending-confirmation precedence, severity escalation, event merging into an open incident, confidence threshold |
| 5 | Spatial engine & road signs | Radius + time-decay colour computation, independence from rule-engine state, multi-sign overlap |
| 6 | Notifications | Stakeholder resolution, cooldown, de-dupe on escalation, SMS failure handling |
| 7 | Incident lifecycle & log | Open/update/close/resolve, 3-hour auto-expiry to `incident_log`, enrichment shape (`_enrich_incident`), timeline construction |
| 8 | Simulator | Single-event injection, moving-target scenario runs, reset |
| 9 | Setup Wizard | All 5 steps (Scenario → Sensors → Signs → Response → Review & Test), end-to-end API replay |
| 10 | Dashboard UI | Live Incidents table/filters/detail drawer, Incident Log page, Road Signs map, GIS, SSE live updates |
| 11 | Admin CRUD | Use Cases, Rules, Stakeholders, Devices, Road Sign Boards, Escalation Policies, Templates |
| 12 | API security | Auth required on mutating admin endpoints, device key never echoed back, producer auth failures logged to `auth_attempts` |
| 13 | Error handling & resilience | Bad/missing fields, duplicate events, offline frontend, MQTT disconnects, server 500s |
| 14 | Cross-browser & responsive | Dashboard at common breakpoints, lucide-react icon regressions (pinned 0.400.0) |
| 15 | Data integrity | Restart/reseed behaviour, JSON-file durability, incident_log never lossy |

### 3.2 Out of scope

- Any computer-vision/inference correctness — the platform explicitly does no inference; a wrong `object_type`/`confidence` from an upstream device is an integration-partner problem, not a platform defect.
- Formal penetration testing (this plan covers functional security/auth only).
- Load testing at real wildlife-corridor sensor-network scale — only indicative concurrency checks are included.
- SMS/WhatsApp delivery guarantees from the Ideabiz gateway itself (only that the platform calls it correctly and handles its failure response).
- Native mobile apps.

### 3.3 Assumptions, dependencies & constraints

- A dedicated staging deployment (or a local `python server.py` + `npm run dev`) with its own `backend/data/` is available; destructive tests (incident-log clearing, device deletion, key rotation) must never run against a live pilot's data.
- The MQTT broker is the **public** `broker.hivemq.com` — there is no guaranteed delivery, no auth at the broker level, and other, unrelated clients share every topic. Tests that publish to it must use throwaway `external_id`s and must not assume exclusivity.
- The SMS gateway will reject non-whitelisted numbers in a sandbox account (`POL0001 — Not a Whitelisted Number` is an expected, not anomalous, response in a test run) — testers must distinguish "SMS correctly attempted and gateway-rejected" from "notification pipeline broken."
- Real mobile devices are useful but not required — the kiosk/display routes and the phone-upload page both work from a desktop browser for test purposes.

### 3.4 Product & project risks

| Risk | Impact | Mitigation in this plan |
| --- | --- | --- |
| Camera/gateway sends the alert and its photo as two separate MQTT messages, in either order, with no shared id | A real incident ships with no evidence photo (already observed in production testing this cycle) | MQT chapter tests all three orderings explicitly against the live `handle_standalone_image`/`_pending_awaiting_image` correlation logic |
| MQTT client has no reconnect-on-disconnect logic | A silent, long-lived outage of the whole ingestion path with no alert to the operator | ENV chapter includes a forced-disconnect recovery case, flagged WATCH |
| Public broker shared with unrelated traffic | A test accidentally processes a real production detection, or vice versa | 3.3 constraint; MQT cases use dedicated throwaway device ids |
| JSON-file storage has no transactional guarantees | Concurrent writes (e.g. two incidents updating at once) could race | DAT chapter includes a concurrency smoke case |
| Incident expiry is a background tick (`_decay_tick`, every 5s) | A timing bug could silently drop or duplicate incidents into the log | NOT/incident-log chapter cross-checks `/api/incidents` vs `/api/incidents/log` row counts before and after expiry |

## 4. Test Approach & Conventions

### 4.1 Test levels and types

| Type | Description | Where |
| --- | --- | --- |
| Functional / contract | Exercise the real ingestion contract (HTTP + MQTT) as a real producer would | ING, MQT, RUL |
| Validation & boundary | Missing fields, out-of-range confidence, malformed JSON, oversized payloads | ING, MQT |
| Negative & error handling | Unknown device, bad key, disabled device, server offline, MQTT disconnect | SEC, ERR |
| Timing / concurrency | Cooldown windows, decay-tick timing, simultaneous image/alert arrival, concurrent incident updates | MQT, NOT, DAT |
| Security / authorisation | Device key required and never echoed, admin-only mutation endpoints | SEC |
| Regression smoke | ENV + ING + RUL golden path re-run after every deploy | Marked P1 |
| Usability / compatibility | Responsive dashboard, lucide-react icon regressions | RSP |

### 4.2 Execution principles

- **One case, one verdict.** Execute steps exactly as written; note any deviation in Remarks.
- **Evidence for every Fail and every WATCH.** Attach the backend console output (this platform prints detailed `[MQTT ALERT]`/`[ENGINE]`/`[MQTT IMAGE]` trace lines — capture them, they are often the only evidence a test needs), a screenshot, and the request/response for API cases.
- **Use fresh devices/zones per section** so cooldown windows and incident merging from earlier tests don't contaminate later counts.
- **Timing-sensitive cases state their wait.** `NOTIFY_COOLDOWN_S` (10 min) and `ALERT_EXPIRY_S` (3h) are real wall-clock waits unless the tester edits `backend/server.py` constants for a faster test run — record which was used.
- **Do not fix while testing.** Log the defect; retest after the fix under a new run entry.
- **Blocked is not Failed.** If a prerequisite (e.g. no registered camera device) fails, mark the dependent case Blocked and reference the blocker.

### 4.3 Priority definitions

| Priority | Meaning | Rule |
| --- | --- | --- |
| P1 | Ingestion contract, incident correctness, notification de-duplication, security | Must pass before any pilot/demo |
| P2 | Important behaviour and validation | Should pass; failures need an accepted-risk note |
| P3 | Cosmetic, minor, or rare-ordering scenarios | Fix when convenient |

### 4.4 Result status codes

| Status | Meaning |
| --- | --- |
| Pass | Actual result matches expected exactly |
| Fail | Any deviation; raise a defect in Appendix B |
| Blocked | Cannot execute — a dependency failed or an environment item is missing |
| N/A | Not applicable in this environment (state why in Remarks) |

### 4.5 Defect severity

| Severity | Definition | Example | Target |
| --- | --- | --- | --- |
| S1 — Critical | A real detection is lost, mis-attributed, or produces no notification; security bypass | Camera photo never reaches the incident (the bug fixed this session); unregistered device accepted | Fix before pilot |
| S2 — Major | Feature broken with no workaround | Incident never auto-expires; sign colour wrong for a live detection | Fix before release |
| S3 — Minor | Works with a workaround or is confusing | Unclear error message; icon renders blank | Next sprint |
| S4 — Trivial | Cosmetic | Spacing, typo | Backlog |

## 5. Entry & Exit Criteria

### 5.1 Entry criteria

- The backend is running (`python server.py`) and `GET /api/system/health` reports `"status":"operational"` with `broker_ok:true`.
- The MQTT client has logged `[MQTT] Connected SUCCESSFUL` to `broker.hivemq.com` since the last restart.
- At least one test device is registered with a known `api_key`, and one test zone/road-sign exist (fresh seed or a prior Setup Wizard run).
- The tester has read chapters 1–4 and understands the evidence/priority/status rules.

### 5.2 Suspension & resumption

Stop testing and notify the QA lead if: the backend is unreachable, the MQTT client shows no successful connect for 5+ minutes, or more than 5 Blocked cases accumulate from one root cause. Resume after the blocking defect is fixed and the ENV + ING smoke cases pass again.

### 5.3 Exit criteria

| # | Criterion | Target |
| --- | --- | --- |
| 1 | Execution coverage — all P1 cases executed | 100% |
| 2 | P1 pass rate (after retest) | 100% |
| 3 | P2 pass rate | ≥ 90%, remaining failures have an accepted workaround |
| 4 | Open S1 defects | 0 |
| 5 | Open S2 defects | 0 for pilot-critical paths (ingestion, notification, incident expiry); others with written Product Owner acceptance |
| 6 | All three MQTT image-correlation orderings (before/during/after) | Pass |
| 7 | All WATCH items in Appendix A | Have a decision: fixed, accepted, or ticketed |
| 8 | Regression smoke (ENV, ING, RUL golden path) re-run on the release build | All pass |

## 6. Test Environment & Test Data

### 6.1 Environments

| Item | Value (fill in before starting) |
| --- | --- |
| Environment name | Staging / local dev |
| Dashboard URL | `http://localhost:5173` (dev) or `http://localhost:8000` (prod-like, built) |
| Backend API base URL | `http://localhost:8000/api` |
| MQTT broker | `broker.hivemq.com:1883` (public — see 3.3) |
| Build / commit id | |
| Backend health (`/api/system/health`) | |
| Storage | Flat JSON, `backend/data/` |
| Test period | |

### 6.2 Test accounts & devices

| Label | Type | Created how | Purpose |
| --- | --- | --- | --- |
| TEST-CAM-01 | camera device | `POST /api/devices` with a throwaway `external_id` (e.g. `st_99_cam_99`) | HTTP + MQTT ingestion cases |
| TEST-CAM-02 | camera device | Same, second id | Multi-device / zone-merge cases |
| ADMIN | dashboard admin | However the deployment bootstraps admin access (no self-service registration exists in this platform — unlike a multi-tenant SaaS, there is no brand/admin account split; confirm the actual auth model in ENV-00x before relying on this row) | Admin CRUD, Setup Wizard |

### 6.3 Test data

| Data | Values | Used for |
| --- | --- | --- |
| Valid `object_type` | `elephant` (seeded use case); any lowercase string the use case's rules reference | Rule matching |
| Confidence boundary values | 0, 59, 60, 61, 100, 101, -1 | Threshold validation |
| Dialog-format phone numbers for stakeholders | Real test numbers must be pre-whitelisted on the Ideabiz sandbox, or expect `POL0001` rejection (not a defect) | Notification dispatch |
| MQTT alert payload shapes | `{station_id, entity_id, alert, value, timestamp}` and the `{object_type, confidence}` HTTP shape | Contract coverage |
| Sample images | A small real JPEG (<200KB) and a deliberately 1-char-truncated base64 string | Image decode + corruption-detection path |
| Long strings | 121/301/1001-char strings for any free-text field (zone name, stakeholder name) | Boundary validation — confirm actual server-side limits, none are documented in the contract |

### 6.4 Tools

Chrome + DevTools (Network, Console); `curl`/Postman for API cases; `backend/scratch/test_mqtt_image.py` and `backend/scratch/test_mqtt_integration.py` (existing repo scripts) or a throwaway `paho-mqtt` publisher script for MQTT cases — always wait for the actual `on_connect` callback before publishing, the public broker's connect handshake can take 10–20s; a screen recorder for SSE/live-update cases.

## 7. Roles, Responsibilities & Effort

| Role | Responsibilities |
| --- | --- |
| QA Lead | Owns this plan, assigns chapters, reviews backend console evidence daily, triages defects, signs off |
| Tester / intern | Executes assigned chapters, captures backend trace output alongside UI evidence, raises defects, retests fixes |
| Developer | Reproduces and fixes defects, answers WATCH items, never closes a defect without tester retest |
| Product Owner | Decides on WATCH items (accept/fix), approves exit |

### Suggested schedule (one tester)

| Day | Chapters |
| --- | --- |
| Day 1 | ENV, Device registration & auth, HTTP ingestion |
| Day 2 | MQTT ingestion (all three image/alert orderings — budget extra time, timing-sensitive) |
| Day 3 | Rule engine, Spatial engine & road signs |
| Day 4 | Notifications, Incident lifecycle & log (3-hour expiry case needs either a long wait or a temporary constant edit) |
| Day 5 | Simulator, Setup Wizard, Dashboard UI |
| Day 6 | Admin CRUD, API security, Error handling, retests, sign-off |

Two testers in parallel roughly halve this; MQTT and notification chapters benefit from one person publishing while the other watches backend logs and the dashboard simultaneously.

## 8. Coverage Summary & Results Dashboard

The Executed / Pass / Fail / Blocked columns are completed by the QA lead as chapters finish.

| Code | Chapter | Cases | P1 | Executed | Pass | Fail | Blocked | Tester / date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ENV | 9. Environment, Deployment & Smoke Checks | 8 | 5 | | | | | |
| DEV | 10. Device Registration & Producer Authentication | 10 | 7 | | | | | |
| ING | 11. Detection Ingestion — HTTP `/api/events` | 12 | 9 | | | | | |
| MQT | 12. MQTT Ingestion, Image Correlation & Liveness | 14 | 10 | | | | | |
| RUL | 13. Rule Engine & Incident Lifecycle | 12 | 10 | | | | | |
| SPA | 14. Spatial Engine & Road Sign Actuation | 8 | 6 | | | | | |
| NOT | 15. Notifications & Stakeholder Dispatch | 8 | 6 | | | | | |
| LOG | 16. Incident Log, Expiry & Archival | 8 | 7 | | | | | |
| SIM | 17. Simulator | 6 | 3 | | | | | |
| WIZ | 18. Setup Wizard | 6 | 4 | | | | | |
| LIV | 19. Dashboard & Live Incidents UI | 8 | 5 | | | | | |
| ADM | 20. Admin CRUD Screens | 8 | 4 | | | | | |
| SEC | 21. API-Level Security & Authorisation | 8 | 7 | | | | | |
| ERR | 22. Error Handling & Resilience | 6 | 3 | | | | | |
| RSP | 23. Cross-Browser, Responsive & Accessibility | 4 | 1 | | | | | |
| DAT | 24. Data Integrity & Deployment Safety | 6 | 5 | | | | | |
| | **TOTAL** | **132** | **92** | | | | | |

## 9. Environment, Deployment & Smoke Checks

Test area code: **ENV** | 8 test cases. Run these first — if any P1 case here fails, stop and fix the environment before continuing.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| ENV-001 | P1 | `GET /api/system/health` | JSON with `status:"operational"`, `broker_ok:true`, `worker_live:true`, `devices_online`/`devices_total`/`active_incidents` numeric, `sse_clients` present | ☐ |
| ENV-002 | P1 | Start `python server.py` fresh (delete `backend/data/` first) | Console shows `[SEED] Initialising Elephant Detection use case...`, `[MQTT] Connected SUCCESSFUL`, and `Dashboard: http://localhost:8000`, no unhandled exceptions | ☐ |
| ENV-003 | P1 | With the backend up, open the dashboard and check DevTools Network for the API host every call goes to | All calls go to the expected backend origin; no stray stale-deployment host from an old `.env`/build | ☐ |
| ENV-004 | P2 | Open `/styleguide` and spot-check every `lucide-react` icon used elsewhere in the app | Page renders with no console errors; no icon renders as blank/`<undefined/>` — lucide-react is pinned at 0.400.0 and `MonitorDot`, `TriangleAlert`, `LayoutGrid`, `Grid` are confirmed missing in that version | ☐ |
| ENV-005 | P1 | Visit `/incidents`, `/map`, `/road-signs`, `/devices`, `/simulator`, `/setup`, `/incidents/log` | Every route renders inside its `ErrorBoundary` — no blank white screen even if a sub-component throws | ☐ |
| ENV-006 | P2 | Disconnect the test machine's network for 30s while the backend is running, then restore | `[MQTT] Connected SUCCESSFUL` is NOT automatically re-logged — confirm whether the client reconnects on its own; if not, this is the no-reconnect-logic gap flagged in Appendix A | ☐ |
| ENV-007 | P2 | Check the browser console on first load of `/`, `/incidents`, `/road-signs` | No red errors caused by the app itself | ☐ |
| ENV-008 | P3 | Visit a non-existent URL, e.g. `/this-page-does-not-exist` | SPA fallback serves `index.html` (per the catch-all route in `server.py`), not a raw 404 JSON | ☐ |

## 10. Device Registration & Producer Authentication

Test area code: **DEV** | 10 test cases. Covers `POST /api/devices`, key issue/regeneration, and the `verify_device_key` gate every producer must clear.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| DEV-001 | P1 | `POST /api/devices` with name/type/use_case_id/zone_id/lat/lng, no `api_key` | Response includes a generated `id` (`DEV-xxxxxx`) and a random `api_key` (128-bit, `secrets.token_hex(16)`); `external_id` is derived from `station_id`+`entity_id` or falls back to the supplied value | ☐ |
| DEV-002 | P1 | Register a device with only `station_id`+`entity_id` (no explicit `external_id`) | `external_id` is auto-set to `{station_id}_{entity_id}` — this is the same identity format the MQTT gateway uses | ☐ |
| DEV-003 | P1 | `POST /api/devices/{id}/regenerate-key` | Returns a fresh plaintext `api_key` once; the old key is immediately invalid for a subsequent `POST /api/events` call | ☐ |
| DEV-004 | P1 | `POST /api/events` with a correct `device_id` but wrong `X-API-Key` | `401` "Device authentication failed: bad_key"; a row is written to `auth_attempts` with `reason:"bad_key"` | ☐ |
| DEV-005 | P1 | `POST /api/events` with an `external_id` that matches no registered device | `400` "Unknown device — register it (by id or external_id) first" | ☐ |
| DEV-006 | P1 | Set a device's `status` to `"disabled"` (via `PUT /api/devices/{id}`), then send a detection with its correct key | `401`/rejected with `reason:"disabled"`; logged to `auth_attempts` | ☐ |
| DEV-007 | P1 | GET a device record via the admin API/UI after creation | The response never echoes the `api_key` in list views where it shouldn't be casually exposed — confirm which endpoints DO legitimately return it (creation, regenerate) vs which list/display it unnecessarily; record actual behaviour, flag WATCH if a list endpoint leaks it | ☐ |
| DEV-008 | P2 | With `MQTT_ENFORCE_AUTH` unset/false, send an MQTT alert for an unregistered `external_id` | Processed anyway ("grace period"), logged `[MQTT AUTH] ... (grace period)` and recorded in `auth_attempts`; confirm this is the intended default for early integration testing, not accidentally left on in a real deployment | ☐ |
| DEV-009 | P2 | Resolve a device by `device_id` when the body ALSO carries a mismatched `external_id` | `_resolve_device` tries `device_id` first; the mismatched `external_id` is ignored — confirm this is the actual precedence and not silently swapped | ☐ |
| DEV-010 | P2 | Register two devices whose `station_id`+`entity_id` collide after concatenation (e.g. `st` + `01_cam01` vs `st_01` + `cam01`) | ⚠ WATCH: `external_id` is a plain string concatenation with no delimiter escaping — confirm whether this can alias two physically different devices to the same identity | ☐ |

## 11. Detection Ingestion — HTTP `/api/events`

Test area code: **ING** | 12 test cases. Reference: `docs/integration-contract.md` §4–5. Every row uses a registered test device unless stated.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| ING-001 | P1 | `POST /api/events` with `device_id`, `object_type:"elephant"`, `confidence:88` | `200` `{event_id, incident_id}`; `incident_id` non-null if the confidence clears the matching rule's threshold | ☐ |
| ING-002 | P1 | Omit `object_type` | `422` — field is REQUIRED per the contract | ☐ |
| ING-003 | P1 | Omit `confidence` | `422` — field is REQUIRED per the contract | ☐ |
| ING-004 | P2 | `confidence: 150` and `confidence: -10` | ⚠ WATCH: the contract states confidence is always 0–100 but confirm whether the server actually validates the range or accepts out-of-bound values silently | ☐ |
| ING-005 | P1 | Send the same `client_event_id` twice | Second call returns the SAME `event_id`/`incident_id` as the first — no duplicate event created, no duplicate notification sent | ☐ |
| ING-006 | P1 | Omit `lat`/`lng` entirely | Event inherits `lat`/`lng` from the registered device record | ☐ |
| ING-007 | P2 | A "manual"-type (phone) device sends its own `lat`/`lng` per event, different each time | `_resolve_event_zone` re-derives the nearest zone per event for `type:"manual"` devices (not pinned to registration-time zone); a camera/fixed device sending `lat`/`lng` is ignored — it always keeps its registered `zone_id` | ☐ |
| ING-008 | P1 | Send `image_url: "https://example.com/snap.jpg"` | Event and (if a new incident opens) the incident both carry that `image_url` unchanged; `GET /api/incidents/{id}` shows `incident_media` resolving to it | ☐ |
| ING-009 | P2 | Omit `image_url` entirely, then a later merged event on the same open incident DOES carry one | Incident backfills `image_url` from the later event (`_run_rule_engine`'s "backfill evidence" logic) — an incident must never get stuck with no evidence once one exists | ☐ |
| ING-010 | P2 | Legacy `POST /api/upload` (multipart file + `object_type`/`confidence`/`device_id`) | File is saved under `/uploads/`, `source:"upload"` on the resulting event, same rule-engine path as any other ingestion | ☐ |
| ING-011 | P1 | `POST /api/upload` with no online camera registered and no `device_id` given | `400` "No online camera registered to attribute this upload to" | ☐ |
| ING-012 | P3 | `raw_payload` containing an `api_key` field | The key is stripped before storage (`body.pop("api_key", None)`) — confirm it never ends up persisted in `detection_events.raw_payload` | ☐ |

## 12. MQTT Ingestion, Image Correlation & Liveness

Test area code: **MQT** | 14 test cases. This chapter exists because of a real production incident this cycle: the camera gateway publishes the detection alert and its photo as two separate MQTT messages, in either order, with no shared id — and the original code silently dropped the image. Every ordering below must be tested against the live backend console output, not just the final dashboard state, because the trace lines (`[MQTT ALERT]`, `[MQTT IMAGE]`, `[MQTT RAW IMAGE]`, `[ENGINE]`) are the only way to distinguish "never arrived" from "arrived and got lost."

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| MQT-001 | P1 | Publish a valid alert JSON (`station_id`, `entity_id`, `alert`, `value`) to the alerts topic for a registered test device | Console logs `[MQTT ALERT] from '<ext_id>': payload=...KB, has_image_url=False, has_raw_img=False`, then `[ENGINE] ... → INC-xxxxxx`, then `[MQTT] Successfully ingested event` | ☐ |
| MQT-002 | P1 | Publish the same alert JSON with `image_url` set to a hosted URL | `has_image_url=True` in the trace line; the resulting incident's `incident_media` resolves to that URL directly, no decode step | ☐ |
| MQT-003 | P1 | Publish an alert JSON with a base64 image under the `image` key | `has_raw_img=True`; `[MQTT IMAGE] Decoded and saved Base64 image: /uploads/...` is logged; the incident's photo is the decoded file | ☐ |
| MQT-004 | P1 | Publish a base64 image deliberately truncated by 1 character (see `backend/scratch/test_mqtt_image.py --corrupt`) | `_assert_valid_image` rejects it via Pillow; `[MQTT IMAGE] FAILED to decode...` is logged with a size comparison; falls back to `/static/placeholder.jpg`, never silently saves a corrupt file | ☐ |
| MQT-005 | P1 — regression | **Image arrives BEFORE the alert.** Publish a raw base64 image to the image topic, wait 2s, then publish the alert JSON for the same device with no image field | `[MQTT RAW IMAGE] Buffered for the next alert...`, then on the alert: `[MQTT IMAGE] Claimed pending standalone image for '<ext_id>': ...`; the resulting incident has the real photo, not a placeholder | ☐ |
| MQT-006 | P1 — regression | **Image arrives DURING the alert's (slow) ingestion.** Publish the alert first (ensure it will take several seconds — e.g. a stakeholder SMS retry loop is in flight), then publish the raw image before `[MQTT] Successfully ingested event` prints | `[MQTT IMAGE] Claimed a buffered image that arrived during ingestion for <event_id> / <incident_id>: ...`; the incident ends up with the photo despite the race | ☐ |
| MQT-007 | P1 — regression | **Image arrives AFTER the alert is fully ingested**, within the 30s correlation TTL | `[MQTT IMAGE] Backfilled late-arriving image onto <event_id> / <incident_id>: ...`; the already-created incident is PATCHED with the image and an `incident_updated` SSE event is broadcast (dashboard updates live, no refresh needed) | ☐ |
| MQT-008 | P2 | Image arrives more than 30s (`PENDING_IMAGE_TTL_S`) after the alert, with no other alert in between | Neither claimed nor backfilled — the image is dropped (buffered state expired); confirm this is logged clearly enough to diagnose, not silently lost | ☐ |
| MQT-009 | P1 | Publish an alert for an external_id that is NOT registered | `[MQTT AUTH] rejected '<ext_id>': unknown_device`; no event/incident created; entry written to `auth_attempts`; any buffered image for this device is now orphaned until TTL expiry (expected — register the device first) | ☐ |
| MQT-010 | P2 | Publish a plain-text status payload (e.g. `"ONLINE"`) to the status topic for a registered device | `[MQTT STATUS] Non-JSON liveness payload...`; device's `online`/`last_seen` updated; no detection event created | ☐ |
| MQT-011 | P2 | Publish to the heartbeat topic for `modem-gateway` (not a registered device id) | `[MQTT STATUS] ignored status from unregistered device 'modem-gateway'` — confirm this is expected (the gateway's own liveness beat, not a camera) and not masking a real registration gap | ☐ |
| MQT-012 | P1 | A mobile/"manual" device publishes `lat`/`latitude` and `lng`/`longitude` in the MQTT payload | Coordinates reach `_ingest_event` (this was a prior bug — the MQTT path originally never read them) and the nearest-zone lookup uses them, same as the HTTP path | ☐ |
| MQT-013 | P3 | Publish a raw (non-JSON) base64 blob directly to the alerts topic (not the image topic) | Falls through to the "Case 2" raw-image handler only if it starts with a recognised image signature (`iVBORw`/`/9j/`/`data:image`) or the topic matches; otherwise logged as `[MQTT] Non-JSON payload received` and dropped — confirm it never crashes the listener thread | ☐ |
| MQT-014 | P2 | Incident opens as `CRITICAL`/`HIGH` from an MQTT-originated event | `actuate_led`/`actuate_siren` publish the correct command to `dialog/actuators/signs/<station_id>/command` and (for CRITICAL) `dialog/actuators/sirens/<station_id>/command`; confirm the station_id used matches the registered device, not a hardcoded fallback | ☐ |

## 13. Rule Engine & Incident Lifecycle

Test area code: **RUL** | 12 test cases. Covers `rule_engine.evaluate_event` and `_run_rule_engine`'s open/merge/escalate behaviour.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| RUL-001 | P1 | Send a detection below the matching rule's confidence threshold | No incident opens; event is stored and marked `processed` but `incident_id` is `null` in the response | ☐ |
| RUL-002 | P1 | Send a detection that clears an immediate (single-detection) rule's threshold | Incident opens immediately, status `ACTIVE`, severity per the rule's `on_trigger.incident_severity` | ☐ |
| RUL-003 | P1 | Send a detection matching a rule with `confirmation` configured (dual-detection), only ONE qualifying event | No incident opens yet; event is flagged `pending_confirmation:true`; console logs `[ENGINE] '<rule>' matched — awaiting confirmation` | ☐ |
| RUL-004 | P1 | Send a second qualifying event completing the confirmation window | Incident opens on the second event, `event_ids` includes both contributing events | ☐ |
| RUL-005 | P1 | With an immediate rule already having opened an incident, send an event that also matches a confirmed/dual rule at higher severity for the same zone | **Precedence case** — escalation must not be blocked: incident's severity updates to the higher value, `escalated:true` path triggers, a fresh notification fires even if within cooldown | ☐ |
| RUL-006 | P1 | Two detections in the same zone within the merge window, second at a LOWER confidence than the first | Incident's `confidence` stays at the higher value ("always update confidence to the highest seen so far") | ☐ |
| RUL-007 | P1 | A detection after a previous incident in the same zone was already `CLOSED`/`RESOLVED` | A NEW incident opens — `_mark_events_consumed` ensures the closed incident's events can never silently re-confirm or merge into a new one | ☐ |
| RUL-008 | P2 | A simulated event (`source:"simulation"`) opens an incident | Incident's `simulated:true` flag is set; confirm this is surfaced somewhere in the UI so operators don't confuse a drill with a real alert | ☐ |
| RUL-009 | P1 | `PUT /api/incidents/{id}` to manually change `status` to `CLOSED` | `_broadcast_incident("incident_updated", ...)` fires; SSE clients receive the update live | ☐ |
| RUL-010 | P2 | `POST /api/incidents` (manual creation, no device) | `status` defaults to `ACTIVE`, `source` defaults to `"manual"`, `opened_at` defaults to now — confirm this manual path is intentionally supported and who can call it (no auth check observed on this endpoint — flag WATCH if so) | ☐ |
| RUL-011 | P2 | `GET /api/incidents/{id}` for a non-existent id | `404` | ☐ |
| RUL-012 | P1 | Inspect `_enrich_incident`'s output for a live incident | `incident_id`, `zone`, `confidence` as 0–1 (not 0–100), `timeline` sorted chronologically, `stakeholders` deduped by channel, `rules_triggered`, `hardware` default shape all present — matches exactly what `IncidentDetail.jsx`/`IncidentTable.jsx` expect | ☐ |

## 14. Spatial Engine & Road Sign Actuation

Test area code: **SPA** | 8 test cases. Covers `spatial.compute_states` — sign colour is purely radius + time-decay, computed independently of the rule engine's incident state.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| SPA-001 | P1 | Send a detection within a sign's `propagation_radius_m` | Sign transitions to `WARNING` (RED) within one `_decay_tick` (5s poll) or immediately via `_broadcast_sign_states` after ingestion | ☐ |
| SPA-002 | P1 | Let `red_hold_s` elapse with no further detections | Sign fades to `CAUTION` (AMBER) | ☐ |
| SPA-003 | P1 | Let `amber_hold_s` elapse beyond that | Sign returns to `CLEAR` (GREEN) | ☐ |
| SPA-004 | P1 | A second detection arrives while the sign is still AMBER (within amber_hold but after red_hold) | Sign returns to RED and the hold timers restart — "movement makes the lit zone travel," confirming no per-target tracking confusion | ☐ |
| SPA-005 | P1 | Detection outside any sign's `propagation_radius_m` | All signs stay CLEAR regardless of incident severity | ☐ |
| SPA-006 | P1 | Manually close the incident (`PUT status:CLOSED`) while the detection is still within the red hold window | Sign state is UNAFFECTED by the incident closure — it keeps decaying on its own timer; this proves the spatial engine never reads rule-engine/incident status | ☐ |
| SPA-007 | P2 | Two signs with overlapping radii, one detection in the overlap zone | Both signs actuate to WARNING independently | ☐ |
| SPA-008 | P2 | A detection at exactly the radius boundary | Record actual inclusive/exclusive behaviour of `haversine_m` comparison — boundary case not documented, flag WATCH if inconsistent between signs with different radii | ☐ |

## 15. Notifications & Stakeholder Dispatch

Test area code: **NOT** | 8 test cases. Covers `notifier.dispatch`, the cooldown gate, and SMS failure handling observed live this session (`POL0001 — Not a Whitelisted Number`).

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| NOT-001 | P1 | A new incident opens matching a rule with `notify_stakeholder_ids` set | Each listed stakeholder is notified on every channel configured for them (SMS/WhatsApp); a row appears in `/api/notifications` per channel | ☐ |
| NOT-002 | P1 | A second detection in the SAME zone within `NOTIFY_COOLDOWN_S` (10 min), no severity change | No new notification is sent — console logs `(cooldown)` as the reason; `last_notified_at` unchanged | ☐ |
| NOT-003 | P1 | A detection escalating severity within the cooldown window | A new notification IS sent despite the cooldown — console logs `(escalated)`; `last_notified_severity` updates | ☐ |
| NOT-004 | P2 | Wait past `NOTIFY_COOLDOWN_S` with sustained detections in the zone | A fresh notification round fires — console logs `(cooldown)` as the reason for a NEW round, not suppressed | ☐ |
| NOT-005 | P1 | A stakeholder's phone number is not whitelisted on the sandbox SMS gateway | `[SMS] → <number>: Attempt 1 failed (HTTP Error 400 ... POL0001 ... Not a Whitelisted Number) — retrying`, 3 retries with backoff (2s/4s/6s), then `Failed to send via Ideabiz`; the incident/notification pipeline still completes — an SMS failure must never block incident creation or the response to the producer | ☐ |
| NOT-006 | P2 | Confirm the ingestion request's response time when a stakeholder's SMS fails all 3 retries | The retry backoff (2+4+6=12s) happens inside `notifier.dispatch`, called synchronously from `_ingest_event` — confirm whether this delays the HTTP/MQTT response to the producer by that much, and whether that's acceptable for a real-time alerting SLA; flag WATCH if so | ☐ |
| NOT-007 | P2 | Zero stakeholders configured for the matching rule | Incident still opens; `notifications` list for it is empty; no crash | ☐ |
| NOT-008 | P3 | Message template (`message_template` on the rule) with all placeholders (`{zone_name}`, `{device_name}`, `{confidence}`, `{incident_id}`) | Rendered message has every placeholder substituted, no literal `{...}` left in the sent text | ☐ |

## 16. Incident Log, Expiry & Archival

Test area code: **LOG** | 8 test cases. Covers the `_decay_tick` 3-hour auto-expiry added this cycle: an incident (active or already closed) is archived into the `incident_log` store and removed from `incidents` once `ALERT_EXPIRY_S` (3h) has elapsed since `opened_at`.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| LOG-001 | P1 | Open a new incident, leave it `ACTIVE`, advance past `ALERT_EXPIRY_S` (or temporarily lower the constant for the test run — record which) | Incident disappears from `GET /api/incidents` and the Live Incidents dashboard table; the SAME `id` appears in `GET /api/incidents/log` with `status:"EXPIRED"` and an `expired_at` timestamp | ☐ |
| LOG-002 | P1 | Same, but the incident was manually `CLOSED`/`RESOLVED` before the 3h mark | Archived status is preserved as `"CLOSED"`/`"RESOLVED"` (not overwritten to `"EXPIRED"`) — confirm the status-preservation branch in `_decay_tick` | ☐ |
| LOG-003 | P1 | Compare `GET /api/incidents` + `GET /api/incidents/log` row counts, before and immediately after an expiry tick | No incident is ever counted in both or in neither — archival is atomic from the API consumer's point of view (create-then-delete inside one tick) | ☐ |
| LOG-004 | P1 | Open `/incidents/log` in the dashboard | `IncidentLog.jsx` polls every 15s and shows the archived incidents in the shared `IncidentTable` component, filters work the same as Live Incidents | ☐ |
| LOG-005 | P1 | Click an archived incident's row | `IncidentDetail` opens in `readOnly` mode — footer shows "Archived incident — read-only", no Close/Delete buttons rendered | ☐ |
| LOG-006 | P2 | `GET /api/incidents/{id}` for an id that has already been archived (removed from `incidents`) | `404` — confirm the only way to fetch an archived incident is via `/api/incidents/log`, and that nothing in the UI still links to the now-dead `/api/incidents/{id}` URL for an expired incident | ☐ |
| LOG-007 | P2 | An incident expires WHILE its detail drawer is open on a dashboard client | SSE `incident_expired` event is broadcast with `{incident_id}` — confirm the frontend either closes the drawer gracefully or at least doesn't poll a now-404 endpoint forever | ☐ |
| LOG-008 | P1 | Restart the backend mid-way between two incidents' expiry windows | `_decay_tick` resumes on the 5s poll loop after restart; neither incident is double-archived nor permanently stuck past its expiry time (the tick re-evaluates `opened_at` on every pass, not a one-shot timer) | ☐ |

## 17. Simulator

Test area code: **SIM** | 6 test cases. Covers `/simulator`, `/api/simulate/event`, `/api/simulate/scenario`. The platform must behave identically for simulated and real detections — this chapter proves that claim.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| SIM-001 | P1 | `POST /api/simulate/event` with `use_case_id`, `lat`, `lng` for a use case with at least one placed sensor | `200 {event_id, incident_id, device_id, device_name}`; the nearest device is attributed, `source:"simulation"` on the event | ☐ |
| SIM-002 | P1 | Same, but the use case has NO placed sensors | `400` "This use case has no placed sensors to attribute a detection to" | ☐ |
| SIM-003 | P1 | `POST /api/simulate/scenario` with a multi-point `path`, `steps`, `step_seconds` | A moving-target run starts; each step emits through the real ingestion path (`_sim_emit` → `_ingest_event`); road signs along the path light up and fade exactly as a real moving detection would (cross-check against SPA-004) | ☐ |
| SIM-004 | P2 | `POST /api/simulate/scenario/{run_id}/stop` mid-run | Run stops; no further events are emitted; `404` if `run_id` doesn't exist | ☐ |
| SIM-005 | P1 | `POST /api/simulate/reset` | All simulation-sourced incidents/events/devices are cleared; `_broadcast_sign_states` and a `simulation_reset` SSE event fire so the dashboard reflects the clean state immediately | ☐ |
| SIM-006 | P2 | Run the Setup Wizard's "Run a test detection" (Review step) | Reuses the same simulator injector as `/simulator`'s single-event form — confirm it's genuinely the same code path, not a separate mock | ☐ |

## 18. Setup Wizard

Test area code: **WIZ** | 6 test cases. Covers `/setup`'s 5 steps: Scenario → Sensors → Signs → Response → Review & Test, for a NON-elephant scenario (proving no hardcoding).

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| WIZ-001 | P1 | Step 1 (Scenario): create a brand-new use case with a non-elephant `object_type` (e.g. `"vehicle"`) | Use case, zone(s) created with no residual elephant-specific defaults (labels, default object list) leaking in | ☐ |
| WIZ-002 | P1 | Step 2 (Sensors): place a device on the map, choose type `camera`/`drone`/`manual` etc. | Device is created at the chosen lat/lng, linked to the use case and zone from Step 1 | ☐ |
| WIZ-003 | P1 | Step 3 (Signs): place a road sign, set `propagation_radius_m` | Sign created, immediately visible on `/road-signs` and in `_compute_sign_states` inputs | ☐ |
| WIZ-004 | P1 | Step 4 (Response): configure a rule with stakeholders and severity for the new object type | Rule is created scoped to the new use case — confirm it does NOT also fire for the elephant use case's detections (use-case isolation) | ☐ |
| WIZ-005 | P1 | Step 5 (Review & Test): click "Run a test detection" | A real simulated detection fires through the full pipeline (see SIM-006); the sign lights, an incident opens, in-wizard feedback confirms success — this is the end-to-end proof the whole wizard actually wired things up correctly | ☐ |
| WIZ-006 | P2 | Abandon the wizard partway (e.g. close the tab after Step 2) | Partially-created entities (use case, device) persist as real records — confirm there's no orphaned/half-configured state that breaks later admin screens (e.g. a use case with zero rules) | ☐ |

## 19. Dashboard & Live Incidents UI

Test area code: **LIV** | 8 test cases. Covers `/incidents` (`LiveIncidents.jsx`), the SSE stream, and the 5s polling fallback.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| LIV-001 | P1 | Open Live Incidents, trigger a detection from another tab/device | New incident row appears WITHOUT a manual refresh — via SSE `incident_new`, not waiting for the 5s poll | ☐ |
| LIV-002 | P1 | Stop the backend's SSE stream (or block `/api/stream` in DevTools) while an incident updates server-side | The 5s polling fallback in `useIncidents.js` still picks up the change — confirm the UI is never permanently stale just because SSE dropped | ☐ |
| LIV-003 | P1 | Filter by Severity and Status (the dropdowns in `IncidentTable.jsx`) | List narrows correctly; combining both filters intersects, not unions | ☐ |
| LIV-004 | P1 | Click a row to open the detail drawer, then click "Close incident" | Confirm dialog appears; confirming sets status to `CLOSED` via `PUT`, toast shown, drawer updates | ☐ |
| LIV-005 | P1 | Click "Delete" on an incident in the detail drawer | Confirm dialog warns it's permanent; confirming calls `DELETE /api/incidents/{id}`; row disappears from the list | ☐ |
| LIV-006 | P2 | With the backend unreachable, load `/incidents` fresh | `useIncidents.js` falls back to `MOCK_INCIDENTS` silently — confirm this fallback is clearly distinguishable from real data (or flag WATCH if a tester could mistake mock data for a live incident during a demo) | ☐ |
| LIV-007 | P1 | Open `/road-signs` while a sign is actively WARNING/CAUTION | Map/board view reflects the live colour, matching SPA chapter cases, via the `signs_state` SSE event | ☐ |
| LIV-008 | P2 | Open `/device/:deviceId` (kiosk display) for a device with an active incident in range | Per-device status renders `ALERT` with incident summary; a device with nothing nearby renders `CLEAR` | ☐ |

## 20. Admin CRUD Screens

Test area code: **ADM** | 8 test cases. Covers Use Cases, Rules, Stakeholders, Devices, Road Sign Boards (all on the `CrudShell`/`ui/` design-system shim), plus the still-local-only stubs.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| ADM-001 | P1 | `/admin/rules`: create a rule with `on_trigger` and `on_confirm` actions | Saved rule immediately affects live ingestion (cross-check with RUL chapter) — no restart required | ☐ |
| ADM-002 | P1 | `/admin/rules`: delete a rule referenced by an OPEN incident | Confirm actual behaviour — does the incident keep its stale `rule_id` gracefully (`_rules_triggered` looks it up and falls back to `{}`), or does the detail view break? | ☐ |
| ADM-003 | P1 | `/admin/stakeholders`: create a stakeholder with SMS + WhatsApp channels | Appears as a selectable target in the Rules editor's `notify_stakeholder_ids`; receives notifications per NOT chapter | ☐ |
| ADM-004 | P2 | `/admin/stakeholders`: delete a stakeholder referenced by a rule's `notify_stakeholder_ids` | Confirm the rule doesn't crash notification dispatch — missing stakeholder id should be skipped, not throw | ☐ |
| ADM-005 | P1 | `/admin/devices`: edit a device's `zone_id` | Subsequent events from that device use the NEW zone for rule matching and sign proximity, immediately | ☐ |
| ADM-006 | P1 | `/admin/road-signs`: create/move a sign on the map | New/updated `propagation_radius_m` and position take effect on the next `_decay_tick` (5s) | ☐ |
| ADM-007 | P2 | `/admin/use-cases`: create a second use case with its own zones/rules/stakeholders | Confirm full isolation — an event tagged with use case A's `use_case_id` never matches use case B's rules, even if zones geographically overlap | ☐ |
| ADM-008 | P3 | Hardware Units and Escalation Policies admin screens (per CLAUDE.md, documented as "still local-only stubs, fast follow") | Confirm current actual state matches that description — if they now persist server-side, update this plan; if still stubs, confirm they fail gracefully rather than silently losing data the user thinks was saved | ☐ |

## 21. API-Level Security & Authorisation

Test area code: **SEC** | 8 test cases. This platform has no documented admin-vs-operator login/role split visible in the code reviewed this session — several rows below exist specifically to confirm or disprove that, since an unauthenticated mutating endpoint is a direct S1 risk.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| SEC-001 | P1 | `POST /api/devices`, `POST /api/rules`, `PUT /api/incidents/{id}`, `DELETE /api/incidents/{id}` with NO auth header/cookie/token | ⚠ WATCH: confirm whether these endpoints require any authentication at all in the current build. If not, this is the platform's single biggest security gap and should be an S1 finding, not a WATCH, once confirmed | ☐ |
| SEC-002 | P1 | `POST /api/events` with a correct `api_key` for Device A, but `device_id` of Device B in the body | Confirm `_resolve_device` resolves strictly by the id given, and the presented key is checked against THAT resolved device — a key for one device must never authenticate detections attributed to another | ☐ |
| SEC-003 | P1 | Fetch a device record via any admin list/detail endpoint | `api_key` is either omitted from list responses or, if present, confirm it is genuinely necessary for the admin UI's "copy key" feature and not leaking into a public-facing view | ☐ |
| SEC-004 | P2 | `GET /api/auth-attempts` | Confirm who can see this — it is a security-relevant audit log of rejected producers and arguably should not be openly readable | ☐ |
| SEC-005 | P1 | Disable a device (`status:"disabled"`), then re-attempt ingestion from it over BOTH HTTP and MQTT | Both paths reject consistently — confirm `verify_device_key`'s disabled check is applied uniformly, not just on one ingestion path | ☐ |
| SEC-006 | P2 | Set `MQTT_ENFORCE_AUTH=true` and repeat DEV-008 (unregistered device over MQTT) | Message is now dropped outright (`[MQTT AUTH] rejected ... (not grace period)`), not processed — confirm the env var genuinely flips enforcement and this is documented as the production setting | ☐ |
| SEC-007 | P2 | Cross-site: load the dashboard from an unexpected origin and call the API | Confirm CORS policy (`CORSMiddleware`) — current config allows `allow_origins=["*"]` per the code reviewed; flag WATCH if this is wider than intended for a production deployment handling device keys | ☐ |
| SEC-008 | P3 | SQL/NoSQL injection-style payloads in any free-text field (zone name, stakeholder name) | Storage is flat JSON files, not a queryable database — confirm there's genuinely no injection surface, but check that such payloads don't break JSON serialization/deserialization of `data_store.py` | ☐ |

## 22. Error Handling & Resilience

Test area code: **ERR** | 6 test cases.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| ERR-001 | P1 | Malformed JSON body to `POST /api/events` | `422` with a readable validation error, no raw stack trace returned to the client | ☐ |
| ERR-002 | P1 | Kill the backend process, then publish to MQTT | MQTT client naturally has no listener; on backend restart, confirm whether in-flight/queued messages on the broker (if any, given QoS) are still delivered, or are simply lost (the public broker gives no delivery guarantee across a consumer outage) | ☐ |
| ERR-003 | P1 | Force an exception inside `_decay_tick` (e.g. a malformed `opened_at` in a hand-edited `incidents.json`) | Caught by the tick's own `try/except`, logged as `[DECAY] tick error: ...`, loop continues on the next 5s iteration — one bad incident record must never stop expiry/sign-decay for every other incident | ☐ |
| ERR-004 | P1 | Stop the backend, then load the dashboard fresh | Clear connection-error state in the UI, not an infinite spinner or blank screen; `ErrorBoundary` catches any resulting render error | ☐ |
| ERR-005 | P2 | Corrupt a `backend/data/*.json` file (invalid JSON) and restart | `data_store._load` catches the parse error and returns `[]` rather than crashing the whole backend — confirm this fails safe (empty list) rather than silently losing data that was actually fine, and that it's logged loudly enough to notice | ☐ |
| ERR-006 | P2 | Send 50 detections for the same device within 1 second (burst) | No crash, no duplicate incidents beyond what the merge logic intends (cross-check RUL-006); confirm response times stay reasonable under the SMS-retry-in-the-critical-path condition noted in NOT-006 | ☐ |

## 23. Cross-Browser, Responsive & Accessibility

Test area code: **RSP** | 4 test cases.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| RSP-001 | P1 | Run the smoke path (Live Incidents → filter → open detail → Road Signs → Incident Log) on Chrome, Edge, Firefox | Identical behaviour, no layout breaks, no icon rendering regressions (cross-check ENV-004) | ☐ |
| RSP-002 | P2 | Dashboard at 1920px, 1366px, and a tablet-width (1024px) viewport | NavSidebar and tables reflow without horizontal scroll on content | ☐ |
| RSP-003 | P2 | The kiosk display route (`/device/:deviceId`) on a small/portrait screen, as it would appear on roadside hardware | Layout remains legible full-screen — this view is meant to run unattended on physical signage, so a broken layout here is operationally significant, not cosmetic | ☐ |
| RSP-004 | P3 | Keyboard-only navigation through Live Incidents' filter + detail drawer + confirm dialogs | All actions reachable; Escape closes the drawer/dialogs; focus visible | ☐ |

## 24. Data Integrity & Deployment Safety

Test area code: **DAT** | 6 test cases.

| ID | Pri | Test steps / input | Expected result | Status |
| --- | --- | --- | --- | --- |
| DAT-001 | P1 | Restart the backend with an EXISTING `backend/data/` present | No re-seed occurs; all devices, incidents, rules, and the incident log are exactly as before restart — per CLAUDE.md, `backend/data/` only re-seeds when deleted | ☐ |
| DAT-002 | P1 | Delete `backend/data/` and restart | Clean re-seed of the elephant-detection use case only; no leftover entities from a prior test run's custom use cases/devices | ☐ |
| DAT-003 | P1 | Trigger two concurrent `PUT` updates to the SAME incident from two clients | `data_store.update` reads-modifies-writes the whole file with no locking visible in the code reviewed — confirm whether the slower write silently clobbers the faster one's changes (a real race in flat-file storage); flag WATCH if so | ☐ |
| DAT-004 | P2 | Deploy to a fresh host and confirm `backend/uploads/` and `backend/data/` are on a persistent volume, not ephemeral container storage | All camera photos and incident history survive a container restart/redeploy — cross-check against the deployment architecture discussed this session | ☐ |
| DAT-005 | P1 | Run the exact MQTT image-correlation regression (MQT-005/006/007) against the DEPLOYED instance, not just local dev | Confirms the fix committed this session (`4a0f4ed`) behaves identically once actually deployed — this was the specific gap that caused the real production failure being tested here | ☐ |
| DAT-006 | P2 | Compare `backend/data/incidents.json` + `incident_log.json` row counts before and after a full day of mixed real/simulated traffic | No incident is ever lost between the two files — total count is conserved across the expiry boundary | ☐ |

## Appendix A — Risk Register: Items Flagged by Code Review (WATCH)

Each row was raised while reading the code against the documented contract. The Product Owner decides, per row, whether to fix, accept, or ticket it; the tester still executes the linked case and records what actually happens.

| Case | Pri | Observation | Decision | Owner / ticket |
| --- | --- | --- | --- | --- |
| ENV-006 | P2 | MQTT client has no reconnect-on-disconnect logic — a network blip could silently and permanently kill ingestion until a manual restart. | | |
| DEV-007 | P2 | Confirm no admin list/detail endpoint echoes a device's `api_key` where it isn't needed. | | |
| DEV-008 | P2 | `MQTT_ENFORCE_AUTH` grace period — confirm it is genuinely off by default only for early integration, not left on in production. | | |
| DEV-010 | P2 | `external_id = station_id + entity_id` is plain string concatenation with no delimiter — possible aliasing between two different physical devices. | | |
| ING-004 | P2 | Confirm the server actually range-validates `confidence` (0–100) rather than accepting out-of-bound values silently. | | |
| MQT-008 | P2 | An image arriving >30s after its alert (outside `PENDING_IMAGE_TTL_S`) is dropped with no further visibility beyond a console line — confirm this is acceptable for a real gateway's actual latency profile. | | |
| RUL-010 | P2 | `POST /api/incidents` (manual creation) — confirm it has the same auth gate as every other mutating endpoint. | | |
| NOT-006 | P2 | SMS retry backoff (up to 12s) runs synchronously inside the ingestion request/response cycle — confirm this is acceptable latency for the producer-facing contract. | | |
| LIV-006 | P2 | `useIncidents.js` falls back to mock data silently when the backend is unreachable — risk of a tester or operator mistaking mock incidents for real ones during a demo. | | |
| ADM-002 | P2 | Deleting a rule referenced by an open incident — confirm the incident detail view degrades gracefully. | | |
| ADM-004 | P2 | Deleting a stakeholder referenced by a rule's `notify_stakeholder_ids` — confirm dispatch skips the missing id instead of throwing. | | |
| ADM-008 | P3 | Hardware Units / Escalation Policies admin screens — confirm current persistence state matches CLAUDE.md's "local-only stub" description. | | |
| **SEC-001** | **P1** | **Highest-priority item**: confirm whether mutating admin endpoints (`POST /api/devices`, `POST /api/rules`, `PUT`/`DELETE /api/incidents`) require any authentication at all. If not, this is an S1 security gap, not a WATCH. | | |
| SEC-003 | P1 | Confirm `api_key` never leaks into a list/display endpoint beyond creation and explicit regeneration. | | |
| SEC-004 | P2 | `GET /api/auth-attempts` exposes a security-relevant audit trail — confirm who can read it. | | |
| SEC-007 | P2 | CORS currently allows `allow_origins=["*"]` — confirm this is intentional for the deployment model (device keys travel over this API). | | |
| ERR-002 | P2 | Public MQTT broker gives no delivery guarantee across a backend outage — confirm what (if anything) happens to detections sent while the backend/MQTT client is down. | | |
| DAT-003 | P2 | Flat-JSON `data_store.update` has no locking — confirm whether two concurrent writes to the same record can silently clobber one another. | | |

## Appendix B — Defect Log

One row per defect. Reference the failing case ID and the backend console/evidence capture. Severity per §4.5.

| Defect # | Case ID | Title / summary | Steps to reproduce (short) | Severity | Found by / date | Assigned to | Status | Retest result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

## Appendix C — Test Execution Report & Sign-off

### Summary of results

| Metric | Value |
| --- | --- |
| Build / commit tested | |
| Execution period | |
| Total cases | 132 |
| Executed | |
| Pass | |
| Fail | |
| Blocked / N/A | |
| P1 pass rate | |
| Open defects S1 / S2 / S3 / S4 | |
| MQTT image-correlation regression (MQT-005/006/007) | |
| WATCH items resolved (Appendix A) | |

### Recommendation

☐ GO — all exit criteria met &nbsp;&nbsp; ☐ GO WITH CONDITIONS — listed below &nbsp;&nbsp; ☐ NO-GO

Conditions / comments:

_____________________________________________________________________

_____________________________________________________________________

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| QA Lead | | | |
| Product Owner | | | |
| Head of Engineering | | | |
