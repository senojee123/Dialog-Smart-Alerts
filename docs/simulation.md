# Simulation — demo without hardware

Hardware (cameras/sensors) is weeks out, so the platform ships with a first-class
**Simulator** that exercises the real pipeline. Every simulated detection flows
through the same `POST /api/events` boundary as a real device (tagged
`source="simulation"`), so the behaviour you demo is exactly what production does.

## Using the Simulator (UI)

**Operations → Simulator**

1. Pick a **use case**. Object type + confidence default to its rule (editable).
2. **Single detection** — click the map to drop one detection. The nearest sensor
   is attributed automatically; nearby boards light by proximity.
3. **Moving target** — switch the mode, click the map to lay a **path**, set the
   number of detections and the interval, then **Play**. A target steps along the
   path over time: the RED→AMBER→GREEN trail travels and a dual-confirm rule
   escalates to CRITICAL — live, over SSE.
4. **Reset sim data** wipes every simulated detection/incident/notification. Real
   device & upload data is never touched.

A persistent **“Simulation mode”** banner makes sure simulated data is never
mistaken for live.

The Setup Wizard's **Review** step embeds the same single-detection injector as
“Run a test detection”, so a freshly built scenario verifies itself before you
activate it.

## API

| Method & path | Purpose |
|---|---|
| `POST /api/simulate/event` | one detection: `{use_case_id, object_type, confidence, lat, lng}` |
| `POST /api/simulate/scenario` | moving target: `{use_case_id, object_type, confidence, path:[[lat,lng]…], steps, step_seconds}` |
| `GET /api/simulate/scenarios` | list active/recent runs (status, progress, position) |
| `POST /api/simulate/scenario/{id}/stop` | stop a run |
| `POST /api/simulate/reset` | delete all `source="simulation"` data |

Both event endpoints require the use case to have at least one **placed** sensor
(a device with coordinates) to attribute the detection to.

### Example — quick smoke test

```bash
# single detection on the seeded elephant corridor
curl -s -X POST localhost:8000/api/simulate/event -H 'Content-Type: application/json' \
  -d '{"use_case_id":"UC-001","object_type":"elephant","confidence":90,"lat":6.3818,"lng":81.48}'

# moving target along the corridor (12 detections, 2s apart)
curl -s -X POST localhost:8000/api/simulate/scenario -H 'Content-Type: application/json' \
  -d '{"use_case_id":"UC-001","object_type":"elephant","confidence":80,"steps":12,"step_seconds":2,
       "path":[[6.3805,81.48],[6.3835,81.48]]}'

# wipe simulated data
curl -s -X POST localhost:8000/api/simulate/reset
```

## When real hardware arrives

Nothing here is throwaway. The Simulator is just another **producer** on the
ingestion contract (see [architecture.md](architecture.md)). Real cameras — or the
planned middle ingestion layer — POST to the same `/api/events` with
`source:"device"`/`"ingestion"`. Keep the Simulator for regression demos, load
checks, and training even after hardware is live.
