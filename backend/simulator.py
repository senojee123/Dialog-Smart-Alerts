"""
Scenario simulator.

Produces detection events that go through the SAME ingestion path as a real
device (so what you demo is exactly what production does) — every event is
tagged `source="simulation"` and every derived incident is flagged
`simulated=True`, which makes a clean one-click reset trivial.

Two modes: single event (use-case aware) and scenario run (a moving target
stepped along a path over time). Transport-agnostic: server.py injects an
`emit(body)` coroutine (the real ingestion function).

Stage B1: data access is async via repo.
"""

import asyncio
import uuid

import repo
import spatial

# run_id -> meta dict (includes the asyncio Task under "_task")
_runs: dict[str, dict] = {}


# ── device attribution ────────────────────────────────────────────────────────

async def _placed_devices(use_case_id: str) -> list[dict]:
    return [
        d for d in await repo.get_all("devices")
        if d.get("use_case_id") == use_case_id
        and d.get("lat") is not None and d.get("lng") is not None
    ]


async def use_case_has_sensors(use_case_id: str) -> bool:
    return len(await _placed_devices(use_case_id)) > 0


async def nearest_device(use_case_id: str, lat: float, lng: float) -> dict | None:
    """Closest placed device of this use case — so each detection is attributed
    to a real sensor (a moving target hands off camera→camera automatically)."""
    devices = await _placed_devices(use_case_id)
    if not devices:
        return None
    return min(devices, key=lambda d: spatial.haversine_m(lat, lng, float(d["lat"]), float(d["lng"])))


# ── path interpolation ────────────────────────────────────────────────────────

def _point_along(path: list, fraction: float) -> tuple[float, float]:
    """Point at `fraction` (0..1) of total length along a polyline of [lat,lng]."""
    pts = [(float(p[0]), float(p[1])) for p in path]
    if len(pts) == 1:
        return pts[0]
    segs = [spatial.haversine_m(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            for i in range(len(pts) - 1)]
    total = sum(segs) or 1.0
    target = max(0.0, min(1.0, fraction)) * total
    run = 0.0
    for i, seg in enumerate(segs):
        if run + seg >= target or i == len(segs) - 1:
            t = (target - run) / seg if seg else 0.0
            a, b = pts[i], pts[i + 1]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        run += seg
    return pts[-1]


async def build_event_body(use_case_id: str, lat: float, lng: float,
                           object_type: str, confidence: float) -> dict | None:
    dev = await nearest_device(use_case_id, lat, lng)
    if not dev:
        return None
    return {
        "device_id":   dev["id"],
        "use_case_id": use_case_id,
        "object_type": object_type,
        "confidence":  confidence,
        "lat":         lat,
        "lng":         lng,
    }


# ── scenario runs ─────────────────────────────────────────────────────────────

async def _run(run_id, emit, use_case_id, path, object_type, confidence, step_seconds, steps):
    meta = _runs[run_id]
    try:
        for i in range(steps):
            frac = i / (steps - 1) if steps > 1 else 0.0
            lat, lng = _point_along(path, frac)
            body = await build_event_body(use_case_id, lat, lng, object_type, confidence)
            if body:
                await emit(body)
            meta["emitted"] = i + 1
            meta["position"] = {"lat": lat, "lng": lng}
            if i < steps - 1:
                await asyncio.sleep(step_seconds)
        meta["status"] = "completed"
    except asyncio.CancelledError:
        meta["status"] = "stopped"
        raise
    except Exception as e:
        meta["status"] = "error"
        meta["error"] = str(e)


def start(emit, use_case_id, path, object_type, confidence, step_seconds, steps) -> dict:
    run_id = f"SIM-{uuid.uuid4().hex[:6].upper()}"
    meta = {
        "id": run_id, "use_case_id": use_case_id, "object_type": object_type,
        "confidence": confidence, "steps": steps, "step_seconds": step_seconds,
        "path": path, "status": "running", "emitted": 0, "position": None,
    }
    _runs[run_id] = meta
    meta["_task"] = asyncio.create_task(
        _run(run_id, emit, use_case_id, path, object_type, confidence, step_seconds, steps)
    )
    return _public(meta)


def stop(run_id: str) -> bool:
    meta = _runs.get(run_id)
    if not meta:
        return False
    task = meta.get("_task")
    if task and not task.done():
        task.cancel()
    meta["status"] = "stopped"
    return True


def _public(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k != "_task"}


def list_runs() -> list:
    return [_public(m) for m in _runs.values()]


# ── reset ─────────────────────────────────────────────────────────────────────

async def reset_simulation() -> dict:
    """Remove all simulation-tagged data (events + their incidents + notifications).
    Live (device/upload) data is untouched."""
    for rid in list(_runs.keys()):
        stop(rid)
    _runs.clear()

    events = await repo.get_all("detection_events")
    sim_event_ids = {e["id"] for e in events if e.get("source") == "simulation"}

    incidents = await repo.get_all("incidents")
    sim_incident_ids = {i["id"] for i in incidents if i.get("simulated")}

    notifs = await repo.get_all("notifications")
    removed_notifs = 0
    for n in notifs:
        if n.get("incident_id") in sim_incident_ids:
            if await repo.delete("notifications", n["id"]):
                removed_notifs += 1

    for iid in sim_incident_ids:
        await repo.delete("incidents", iid)
    for eid in sim_event_ids:
        await repo.delete("detection_events", eid)

    return {
        "events_removed":        len(sim_event_ids),
        "incidents_removed":     len(sim_incident_ids),
        "notifications_removed": removed_notifs,
    }
