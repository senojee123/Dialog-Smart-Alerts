# Integration Contract — Detection Intake

**Status:** v1 · **Owner:** Alerting Platform team · **Audience:** Inputs team
(cameras / edge-AI / inference / connectors)

This is the **single source of truth** for the boundary between the *Inputs* side
and the *Alerting Platform*. If something isn't in here, it isn't part of the
contract — raise it as a change (see [§7](#7-versioning--change-control)).

---

## 1. The boundary in one line

> **Detections in, alerts out.** The platform consumes **detection events** and
> produces incidents, notifications and sign actuation. It never sees video
> frames, RTSP streams, or models.

```
  INPUTS TEAM (owns inference)                 ALERTING PLATFORM (owns decisions)
 ┌───────────────────────────────┐           ┌──────────────────────────────────┐
 │ cameras · edge-AI · connectors │  detection │ rule engine → incidents          │
 │ or an upstream AI service      │ ─ event ──►│ → notifications (SMS/WhatsApp/…) │
 │ → produces {object,confidence} │  POST      │ → spatial sign actuation         │
 └───────────────────────────────┘ /api/events │ → live dashboard (SSE)           │
                                                └──────────────────────────────────┘
                                            the line is this HTTP contract ▲
```

## 2. Responsibility split

| Concern | Inputs team | Alerting Platform |
|---|---|---|
| Camera connectivity, RTSP, streams | ✅ | — |
| **All inference** (detect/classify object) | ✅ | — (never) |
| Produce one **detection event** per detection | ✅ | — |
| Map a producer to a registered **device identity** | ✅ | provides the registry + keys |
| Retry / buffering on transient failures | ✅ | provides idempotency |
| Host or supply the evidence **image** | ✅ | stores the URL / file |
| Vendor class → **canonical object_type** mapping | ✅ | defines the canonical list |
| Device registry, geolocation, zones | — | ✅ |
| Rule engine, confirmation, escalation | — | ✅ |
| Notifications, stakeholders, channels | — | ✅ |
| Road-sign / actuator state | — | ✅ |
| Dashboard, SSE, audit | — | ✅ |

**Explicitly NOT the platform's job:** inference, RTSP/stream handling, model
training, frame storage. A "dumb" camera with no detection capability cannot be a
direct input — it must sit behind an edge-AI device or an upstream AI service that
emits detection events.

## 3. Step 1 — Register a device (once per physical sensor)

Every producer device exists in the platform registry and carries credentials +
location. Registration is normally done by a platform admin (dashboard → Devices),
or by the inputs team via the API below.

`POST /api/devices`
```jsonc
{
  "name":        "Camera Trap – B43 km1.0",
  "type":        "camera",          // camera | thermal | drone | acoustic | pressure_pad | manual
  "use_case_id": "UC-001",          // which scenario this feeds
  "zone_id":     "ZONE-B43",        // which zone (carries the location story)
  "lat": 6.3805, "lng": 81.4800,    // platform owns location; events inherit it
  "vendor":      "camthink",        // optional: camthink | hikvision | ezviz | milesight | …
  "external_id": "E4:5F:01:AA:BB:CC" // optional: the producer's native id (MAC/serial)
}
```
Response includes the **`id`** and a generated **`api_key`** — the two things the
producer needs:
```json
{ "id": "DEV-2B12C3", "api_key": "dev-key-38d5b38a", "external_id": "E4:5F:01:AA:BB:CC", "...": "..." }
```
> The platform owns **location**. Cameras generally don't send GPS; the event
> inherits `lat/lng` from the registered device. Send per-event coordinates only
> for mobile producers (e.g. a drone).

## 4. Step 2 — Send a detection

`POST /api/events`
**Auth:** header `X-API-Key: <device api_key>` (or `api_key` in the body).

```jsonc
{
  "device_id":       "DEV-2B12C3",        // identify by our id …
  // "external_id":  "E4:5F:01:AA:BB:CC", // … OR by the producer's native id
  "object_type":     "elephant",          // REQUIRED — canonical class (lowercase)
  "confidence":      88.0,                 // REQUIRED — 0–100
  "lat": 6.3805, "lng": 81.4800,          // optional — defaults to the device location
  "image_url":       "https://…/snap.jpg", // optional — evidence (you host it)
  "bbox":            [x, y, w, h],          // optional — detection box
  "captured_at":     "2026-06-19T08:24:01Z",// optional — when the camera saw it (ISO-8601 UTC)
  "client_event_id": "cam12-000457",       // optional but recommended — your unique id (idempotency)
  "vendor":          "camthink",           // optional — provenance
  "raw_payload":     { }                    // optional — original vendor payload, stored verbatim
}
```

**Success** `200`:
```json
{ "event_id": "EVT-23BB7613", "incident_id": "INC-C89115" }
```
`incident_id` is `null` when the event matched no rule, or is still awaiting
confirmation.

**Errors**

| Code | Meaning | Action |
|---|---|---|
| `400` | unknown device (bad `device_id`/`external_id`) | register the device first |
| `401` | missing/invalid `api_key` for that device | send the correct key |
| `422` | malformed JSON / wrong types | fix the payload |

## 5. Field rules (the important details)

- **`object_type`** — lowercase canonical string the rules match (`elephant`,
  `vehicle`, `person`, `fire`…). The inputs team maps each vendor's class to one of
  these. The canonical list per use case is owned by the platform (ask, or read the
  use case's rules).
- **`confidence`** — always **0–100**. Normalise vendor scales to this.
- **Idempotency** — set **`client_event_id`** and you may safely retry; the platform
  returns the existing event instead of creating a duplicate. **Do not** re-POST the
  *same* sighting as new events to "keep it alive" — the platform already merges
  repeated detections in a zone into one incident and de-storms notifications
  (it alerts on open / escalation / cooldown only).
- **Images** — three options: (a) send `image_url` you host; (b) `POST /api/upload`
  (multipart `file` + `object_type`/`confidence`/`device_id`) and we store it;
  (c) omit. The platform never decodes or analyses pixels.
- **Time** — `captured_at` is informational; the platform timestamps on receipt.
  Use ISO-8601 UTC.

## 6. What the platform does next (so you understand the consequences)

`event → rule match (object_type + confidence) → incident opened/escalated →
notifications + spatial sign actuation → dashboard/SSE`.

So three of your fields directly drive behaviour: **`object_type`** (which rule),
**`confidence`** (does it clear the threshold / confirmation), **location** (which
sign boards light). Everything else is evidence/metadata.

## 7. Versioning & change control

- This contract is **v1**. Additive, backward-compatible fields can be added without
  a version bump; **breaking** changes get a new version and a migration note.
- Propose changes via the platform team (PR to this file). Don't rely on undocumented
  fields — `raw_payload` is the safe place for anything vendor-specific.

## 8. Testing without hardware

The platform behaves **identically** for simulated and real detections (same intake
path), so you can integrate and verify before any camera ships:

```bash
# 1. register a sandbox device (returns id + api_key)
curl -s -X POST localhost:8000/api/devices -H 'Content-Type: application/json' \
  -d '{"name":"Sandbox Cam","type":"camera","use_case_id":"UC-001","zone_id":"ZONE-B43",
       "lat":6.3805,"lng":81.48,"vendor":"camthink","external_id":"TEST-MAC-01"}'

# 2. send a detection with the returned api_key
curl -s -X POST localhost:8000/api/events \
  -H 'Content-Type: application/json' -H 'X-API-Key: <api_key>' \
  -d '{"external_id":"TEST-MAC-01","object_type":"elephant","confidence":88,"client_event_id":"t-1"}'
# -> {"event_id":"…","incident_id":"…"}
```
Watch the result live on the dashboard (Live Incidents + Road Signs). The built-in
**Simulator** (`/simulator`) does exactly this for moving targets — see
[simulation.md](simulation.md).

## 9. Reference

- Pipeline + the `source` field: [architecture.md](architecture.md)
- Multi-vendor adapters (CamThink/Hikvision/EZVIZ/Milesight) all normalise **to this
  contract** and POST as `source:"ingestion"` — one core, many thin connectors.
