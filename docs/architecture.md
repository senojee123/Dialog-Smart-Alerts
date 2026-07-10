# Architecture

Dialog Smart Alerts is a **use-case-driven** notification & alerting platform. The
elephant scenario is seeded *data*, not hardcoded logic — the same engine runs any
scenario you build in the Setup Wizard.

## The pipeline

```
                          ┌──────────────────────────────────────────────┐
   PRODUCERS              │                 THE ENGINE                   │      CONSUMERS
                          │                                              │
 real device ─┐          │   rule_engine ─► incident ─► notifier        │   ┌─ dashboard (SSE)
 phone upload ─┼─► POST ──┼─► (conditions   (open /     (SMS/WhatsApp/   ├──►├─ road signs
 simulator ───┤  /api/   │   + confirm)    escalate)    Email, sim'd)   │   └─ stakeholders
 (future)     │  events  │        └────► spatial ─► sign states (R/A/G) │
 ingestion ───┘          │                (radius + time decay)         │
                          └──────────────────────────────────────────────┘
```

Every detection — whatever its origin — enters through **one function**,
`_ingest_event(body, source)` in [`backend/server.py`](../backend/server.py). It:

1. resolves the `device_id` to a registered device (gives the event its
   `use_case_id`, `zone_id`, and a location for the spatial engine),
2. stores the event (tagged with its `source`),
3. runs the rule engine → opens/updates an incident + dispatches notifications,
4. recomputes sign states and broadcasts everything over SSE.

Because it is the single boundary, **simulated and real detections behave
identically** — what you demo is what production does.

## The ingestion contract

`POST /api/events`

```jsonc
{
  "device_id":   "DEV-001",      // required — must be a registered device
  "object_type": "elephant",     // what was detected
  "confidence":  88.0,           // 0–100
  "lat": 6.3818, "lng": 81.4800, // optional; defaults to the device location
  "image_url":   "/uploads/x.jpg", // optional evidence
  "use_case_id": "UC-001",       // optional; normally inherited from the device
  "source":      "device"        // device | upload | simulation | ingestion
}
```

The public endpoint authenticates external producers with the device's **`api_key`**
(`X-API-Key` header), resolves the device by our id **or** the producer's
**`external_id`** (MAC/serial), and de-duplicates retries by **`client_event_id`**.
The full producer-facing spec — the document to hand the inputs team — is
[**integration-contract.md**](integration-contract.md).

The `source` field is the seam for what's coming:

| Producer | `source` | Status |
|---|---|---|
| Real camera/sensor POSTing directly | `device` | when hardware arrives (~2–3 wks) |
| Phone-camera demo (`/upload`) | `upload` | working |
| Built-in Simulator | `simulation` | working |
| Middle ingestion layer (normalises vendor payloads → this contract) | `ingestion` | future |

**Adding real hardware changes nothing downstream.** The camera (or the middle
layer) just POSTs to `/api/events` with `source:"device"`/`"ingestion"`. Rules,
spatial actuation, incidents, notifications and the dashboard are unchanged.

## Components (`backend/`)

| File | Responsibility |
|---|---|
| `server.py` | FastAPI app: CRUD, the `_ingest_event` boundary, SSE, simulator routes, SPA serving |
| `rule_engine.py` | match conditions, evaluate confirmation windows → `(rule, action)` |
| `spatial.py` | sign state from radius + time-decay (haversine); **authority for sign colour** |
| `notifier.py` | simulated SMS/WhatsApp/Email dispatch (logged to `notifications`) |
| `simulator.py` | use-case-aware single events + moving-target scenario runs; sim reset |
| `data_store.py` | generic JSON-file CRUD (`backend/data/`, gitignored) |
| `seed.py` | the Elephant Detection use case (only when `data/` is empty) |

## Incident & notification precision

- **One incident per open situation.** A new qualifying event in the same
  zone/use-case folds into the open incident and only **escalates** severity.
- **No alert storms.** Notifications fire on first open, on a severity increase,
  or after a cooldown (`NOTIFY_COOLDOWN_S`, default 600 s) — never on every event.
- **Confirmation is scoped.** Events already consumed by a closed/resolved
  incident don't count toward confirming a new one (so a closed incident can't
  instantly re-confirm CRITICAL).

## Sign actuation

Sign colour is derived **purely** by `spatial.py` from `(distance, age)` of recent
events — a detection within `propagation_radius_m` lights boards **RED** for
`red_hold_s`, fades to **AMBER** until `amber_hold_s`, then **GREEN**. A moving
target makes the lit region travel with an amber trail, with no per-target
tracking. (Rules no longer push sign states — that path was inert and has been
removed from wizard-generated rules.)

## Live updates (SSE)

`GET /api/stream` emits `{type, data}` frames: `incident_new`, `incident_updated`,
`event_received`, `signs_state`, `simulation_reset`. The dashboard takes a REST
snapshot first, then applies stream deltas (idempotent on `updated_at`).
