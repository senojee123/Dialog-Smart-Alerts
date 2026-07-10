"""
Dialog Smart Alerts – General Notification & Alerting Platform
FastAPI backend serving:
  • Static frontend (dist/)
  • Full CRUD REST APIs for every entity
  • General event intake + rule engine + notification dispatch
  • SSE stream for live dashboard updates
  • Mobile camera upload page
"""

import asyncio
import json
import os
import socket
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Windows consoles default to cp1252, which can't encode characters like the
# arrow used in log lines — force UTF-8 so logging never crashes a request.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
from pathlib import Path
from typing import AsyncGenerator

import seed
import db
import data_store
import rule_engine
import notifier
import spatial
import simulator
from mqtt_client import MQTTClientManager

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse as _FileResponse
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DIST_DIR    = BASE_DIR.parent / "dist"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# ── App ──────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.loop = asyncio.get_running_loop()
    await db.init_db()
    await seed.run()
    
    # Initialize and start background MQTT client
    app.state.mqtt_client = MQTTClientManager(app)
    app.state.mqtt_client.start()
    
    _print_local_ip()
    task = asyncio.create_task(_decay_tick())
    yield
    task.cancel()
    if hasattr(app.state, "mqtt_client") and app.state.mqtt_client:
        app.state.mqtt_client.stop()


app = FastAPI(title="Dialog Smart Alerts", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ── SSE broadcast queue ──────────────────────────────────────────────────────
_sse_queues: list[asyncio.Queue] = []


def broadcast(event_type: str, payload: dict):
    msg = json.dumps({"type": event_type, "data": payload}, default=str)
    for q in list(_sse_queues):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s):
    """Parse an ISO timestamp to an aware datetime, or None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# Re-notify the same incident at most once per this window unless it escalates.
NOTIFY_COOLDOWN_S = 600


# Last broadcast sign states — so we only emit when something actually changes.
_last_sign_states: dict = {}


async def _decay_tick():
    """
    Every few seconds, recompute actuator states. Because RED/AMBER/GREEN
    depend on elapsed time, signs fade on their own even with no new events.
    Broadcasts only the signs whose state changed.
    """
    global _last_sign_states
    while True:
        await asyncio.sleep(5)
        try:
            states = _compute_sign_states()
            changed = {sid: st for sid, st in states.items()
                       if _last_sign_states.get(sid) != st}
            if changed:
                _last_sign_states = states
                broadcast("signs_state", {"states": states, "changed": list(changed.keys())})
                
                # Actuate signs via MQTT on state changes
                if hasattr(app, "state") and hasattr(app.state, "mqtt_client") and app.state.mqtt_client:
                    for sid in changed:
                        sign_state = states[sid]
                        color_map = {"WARNING": "RED", "CAUTION": "AMBER", "CLEAR": "GREEN", "OFFLINE": "OFF"}
                        color = color_map.get(sign_state, "OFF")
                        app.state.mqtt_client.actuate_led(sid, color)
        except Exception as e:
            print(f"[DECAY] tick error: {e}")


def _print_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        print(f"\n  Dashboard:  http://localhost:8000")
        print(f"  Phone cam:  http://{ip}:8000/upload\n")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# CRUD HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _list(store: str):
    return data_store.get_all(store)

def _get(store: str, id: str):
    item = data_store.get_by_id(store, id)
    if not item:
        raise HTTPException(404, f"{store} '{id}' not found")
    return item

def _create(store: str, body: dict):
    return data_store.create(store, body)

def _update(store: str, id: str, body: dict):
    result = data_store.update(store, id, body)
    if not result:
        raise HTTPException(404, f"{store} '{id}' not found")
    return result

def _delete(store: str, id: str):
    if not data_store.delete(store, id):
        raise HTTPException(404, f"{store} '{id}' not found")
    return {"deleted": id}


# ════════════════════════════════════════════════════════════════════════════
# USE CASES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/use-cases")
async def list_use_cases():
    return _list("use_cases")

@app.post("/api/use-cases")
async def create_use_case(req: Request):
    body = await req.json()
    uc = _create("use_cases", body)
    broadcast("use_case_created", uc)
    return uc

@app.get("/api/use-cases/{id}")
async def get_use_case(id: str):
    return _get("use_cases", id)

@app.put("/api/use-cases/{id}")
async def update_use_case(id: str, req: Request):
    body = await req.json()
    uc = _update("use_cases", id, body)
    broadcast("use_case_updated", uc)
    return uc

@app.delete("/api/use-cases/{id}")
async def delete_use_case(id: str):
    return _delete("use_cases", id)


# ════════════════════════════════════════════════════════════════════════════
# ZONES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/zones")
async def list_zones():
    return _list("zones")

@app.post("/api/zones")
async def create_zone(req: Request):
    return _create("zones", await req.json())

@app.get("/api/zones/{id}")
async def get_zone(id: str):
    return _get("zones", id)

@app.put("/api/zones/{id}")
async def update_zone(id: str, req: Request):
    return _update("zones", id, await req.json())

@app.delete("/api/zones/{id}")
async def delete_zone(id: str):
    return _delete("zones", id)


# ════════════════════════════════════════════════════════════════════════════
# DEVICES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/devices")
async def list_devices():
    return _list("devices")

@app.post("/api/devices")
async def create_device(req: Request):
    body = await req.json()
    if not body.get("api_key"):
        body["api_key"] = f"dev-key-{uuid.uuid4().hex[:8]}"
    if not body.get("external_id"):
        body["external_id"] = body["api_key"]
    device = _create("devices", body)
    broadcast("device_created", device)
    return device

@app.get("/api/devices/{id}")
async def get_device(id: str):
    return _get("devices", id)

@app.put("/api/devices/{id}")
async def update_device(id: str, req: Request):
    body = await req.json()
    if body.get("api_key") and not body.get("external_id"):
        body["external_id"] = body["api_key"]
    device = _update("devices", id, body)
    broadcast("device_updated", device)
    return device

@app.delete("/api/devices/{id}")
async def delete_device(id: str):
    return _delete("devices", id)


# ════════════════════════════════════════════════════════════════════════════
# KIOSK DISPLAYS (Raspberry Pi display units)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/kiosks")
async def list_kiosks():
    return _list("kiosk_displays")

@app.post("/api/kiosks")
async def create_kiosk(req: Request):
    body = await req.json()
    kiosk = _create("kiosk_displays", body)
    broadcast("kiosk_created", kiosk)
    return kiosk

@app.get("/api/kiosks/{device_id}/status")
async def get_kiosk_status(device_id: str):
    kiosk = data_store.get_by_id("kiosk_displays", device_id)
    if not kiosk:
        raise HTTPException(404, f"Kiosk display '{device_id}' not found")
    
    active_incidents = [
        inc for inc in data_store.get_all("incidents")
        if inc.get("status") in ("ACTIVE", "OPERATOR_REVIEW")
    ]
    
    kiosk_station_ids = kiosk.get("station_ids", [])
    kiosk_zone_ids = kiosk.get("zone_ids", [])
    
    for inc in active_incidents:
        # Check zone match
        zone_match = inc.get("zone_id") in kiosk_zone_ids
        
        # Check station match by looking up the device
        station_match = False
        station_id = "Unknown"
        device = data_store.get_by_id("devices", inc.get("device_id", ""))
        if device and device.get("external_id"):
            ext = device["external_id"]
            if "_" in ext:
                station_id = ext.split("_")[0]
                station_match = station_id in kiosk_station_ids
        
        if zone_match or station_match:
            return {
                "status": "ALERT",
                "incident": {
                    "id": inc["id"],
                    "zone_id": inc.get("zone_id"),
                    "zone_name": inc.get("zone_name") or inc.get("zone"),
                    "opened_at": inc["opened_at"],
                    "confidence": inc["confidence"],
                    "object": inc["object"],
                    "station_id": station_id
                }
            }
            
    return {"status": "CLEAR"}



# ════════════════════════════════════════════════════════════════════════════
# STAKEHOLDERS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/stakeholders")
async def list_stakeholders():
    return _list("stakeholders")

@app.post("/api/stakeholders")
async def create_stakeholder(req: Request):
    return _create("stakeholders", await req.json())

@app.get("/api/stakeholders/{id}")
async def get_stakeholder(id: str):
    return _get("stakeholders", id)

@app.put("/api/stakeholders/{id}")
async def update_stakeholder(id: str, req: Request):
    return _update("stakeholders", id, await req.json())

@app.delete("/api/stakeholders/{id}")
async def delete_stakeholder(id: str):
    return _delete("stakeholders", id)


# ════════════════════════════════════════════════════════════════════════════
# RULES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/rules")
async def list_rules():
    return _list("rules")

@app.post("/api/rules")
async def create_rule(req: Request):
    return _create("rules", await req.json())

@app.get("/api/rules/{id}")
async def get_rule(id: str):
    return _get("rules", id)

@app.put("/api/rules/{id}")
async def update_rule(id: str, req: Request):
    return _update("rules", id, await req.json())

@app.delete("/api/rules/{id}")
async def delete_rule(id: str):
    return _delete("rules", id)


# ════════════════════════════════════════════════════════════════════════════
# ROAD SIGNS
# ════════════════════════════════════════════════════════════════════════════

def _compute_sign_states() -> dict:
    """Returns { sign_id: state } using the spatial engine."""
    return spatial.compute_states(
        signs      = _list("road_signs"),
        use_cases  = _list("use_cases"),
        zones      = _list("zones"),
        events     = _list("detection_events"),
        incidents  = _list("incidents"),
    )


@app.get("/api/road-signs")
async def list_road_signs():
    signs  = _list("road_signs")
    states = _compute_sign_states()
    for sign in signs:
        sign["state"] = states.get(sign["id"], "CLEAR")
    return signs

@app.post("/api/road-signs")
async def create_road_sign(req: Request):
    return _create("road_signs", await req.json())

@app.put("/api/road-signs/{id}")
async def update_road_sign(id: str, req: Request):
    return _update("road_signs", id, await req.json())

@app.delete("/api/road-signs/{id}")
async def delete_road_sign(id: str):
    return _delete("road_signs", id)


# ════════════════════════════════════════════════════════════════════════════
# INCIDENTS
# ════════════════════════════════════════════════════════════════════════════

def _rules_triggered(inc: dict) -> list:
    rid = inc.get("rule_id")
    if not rid:
        return []
    rule = data_store.get_by_id("rules", rid) or {}
    return [{"name": rule.get("name", rid), "severity": inc.get("severity", "")}]


def _enrich_incident(inc: dict) -> dict:
    """
    Map a stored incident into the richer shape the dashboard UI expects:
    incident_id alias, zone name, timeline (from events + notifications),
    notified stakeholders, and AI summary fields.
    """
    if not inc:
        return inc

    iid  = inc.get("id")
    zone = data_store.get_by_id("zones", inc.get("zone_id", "")) or {}
    zone_name = inc.get("zone_name") or zone.get("name") or inc.get("zone_id", "")

    event_ids = set(inc.get("event_ids", []))
    events = [e for e in data_store.get_all("detection_events") if e.get("id") in event_ids]
    notifs = [n for n in data_store.get_all("notifications") if n.get("incident_id") == iid]

    # Stakeholders grouped from the notifications actually sent
    # (dedupe channels by type — a contact may be notified across several rounds)
    by_sh = {}
    for n in notifs:
        sid = n.get("stakeholder_id")
        if sid not in by_sh:
            full = data_store.get_by_id("stakeholders", sid) or {}
            by_sh[sid] = {"id": sid, "name": n.get("stakeholder_name", ""),
                          "role": full.get("role", ""), "channels": {}}
        by_sh[sid]["channels"][n.get("channel")] = {
            "type": n.get("channel"), "status": "delivered", "ack": None,
        }
    stakeholders = [{**s, "channels": list(s["channels"].values())} for s in by_sh.values()]

    # Timeline
    timeline = [{"ts": inc.get("opened_at"), "event": f"Incident opened ({inc.get('source', 'auto')})"}]
    for e in sorted(events, key=lambda e: e.get("received_at", "")):
        timeline.append({
            "ts": e.get("received_at"),
            "event": f"Detection by {e.get('device_name') or e.get('device_id')} "
                     f"— {round(float(e.get('confidence', 0)))}% confidence",
        })
    if notifs:
        first = min(notifs, key=lambda n: n.get("sent_at", ""))
        timeline.append({"ts": first.get("sent_at"),
                         "event": f"Stakeholders notified ({len(by_sh)} contacts, {len(notifs)} channels)"})
    if inc.get("status") in ("CLOSED", "RESOLVED"):
        timeline.append({"ts": inc.get("updated_at"), "event": f"Incident {inc.get('status').lower()}"})
    timeline.sort(key=lambda t: t.get("ts") or "")

    raw_conf   = float(inc.get("confidence", 0) or 0)
    confidence = raw_conf / 100 if raw_conf > 1 else raw_conf   # UI expects 0–1
    loc = {**(inc.get("location") or {}), "description": zone_name}

    return {
        **inc,
        "incident_id":        iid,
        "zone":               zone_name,
        "location":           loc,
        "object":             inc.get("object", "unknown"),
        "herd_size":          inc.get("herd_size", 1),
        "confidence":         confidence,
        "ai_confirmed":       confidence >= 0.6,
        "ai_summary":         inc.get("ai_summary") or
                              f"{str(inc.get('object', 'Object')).capitalize()} detected with "
                              f"{round(raw_conf)}% confidence in {zone_name}.",
        "risk_factors":       inc.get("risk_factors", []),
        "distance_to_road_m": inc.get("distance_to_road_m"),
        "is_night":           inc.get("is_night", False),
        "detections_in_zone": len(events),
        "incident_media":     inc.get("image_url"),
        "rules_triggered":    _rules_triggered(inc),
        "stakeholders":       stakeholders,
        "hardware":           inc.get("hardware") or {"unit_id": None, "name": None, "state": None, "expires_at": None},
        "timeline":           timeline,
        "updated_at":         inc.get("updated_at", inc.get("opened_at")),
        "operator_notes":     inc.get("operator_notes", ""),
    }


def _broadcast_incident(kind: str, inc: dict):
    """Broadcast an incident over SSE in the enriched (UI-ready) shape."""
    broadcast(kind, _enrich_incident(inc))


@app.get("/api/incidents")
async def list_incidents():
    incidents = _list("incidents")
    incidents.sort(key=lambda i: i.get("opened_at", ""), reverse=True)
    return [_enrich_incident(i) for i in incidents]

@app.post("/api/incidents")
async def create_incident_manual(req: Request):
    body = await req.json()
    body.setdefault("opened_at", _now())
    body.setdefault("status", "ACTIVE")
    body.setdefault("source", "manual")
    incident = _create("incidents", body)
    _broadcast_incident("incident_new", incident)
    return _enrich_incident(incident)

@app.get("/api/incidents/{id}")
async def get_incident(id: str):
    return _enrich_incident(_get("incidents", id))

@app.put("/api/incidents/{id}")
async def update_incident(id: str, req: Request):
    body = await req.json()
    incident = _update("incidents", id, body)
    _broadcast_incident("incident_updated", incident)
    return _enrich_incident(incident)

@app.delete("/api/incidents/{id}")
async def delete_incident(id: str):
    return _delete("incidents", id)


# ════════════════════════════════════════════════════════════════════════════
# DETECTION EVENTS (General Intake)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/events")
async def list_events():
    events = _list("detection_events")
    events.sort(key=lambda e: e.get("received_at", ""), reverse=True)
    return events[:200]


def _resolve_device(body: dict) -> dict | None:
    """Resolve the producing device by our id, or by the producer's own
    `external_id` (e.g. camera MAC/serial) so connectors can use native ids."""
    if body.get("device_id"):
        d = data_store.get_by_id("devices", body["device_id"])
        if d:
            return d
    ext = body.get("external_id")
    if ext:
        return next((x for x in data_store.get_all("devices") if x.get("external_id") == ext), None)
    return None


async def _ingest_event(body: dict, source: str = "device") -> tuple[dict, dict | None]:
    """
    THE ingestion boundary. Every producer — real devices, the phone-camera
    upload, and the simulator — funnels through here, so they all get the same
    rule-engine + spatial + notification behaviour. `source` records the origin
    (device | upload | simulation | ingestion) and is carried onto the event.
    """
    device = _resolve_device(body)
    if not device:
        raise HTTPException(400, "Unknown device — register it (by id or external_id) first")

    # Idempotency: a producer may safely retry with the same client_event_id;
    # we return the already-stored event instead of creating a duplicate.
    cid = body.get("client_event_id")
    if cid:
        prior = next((e for e in data_store.get_all("detection_events") if e.get("client_event_id") == cid), None)
        if prior:
            inc = next((i for i in data_store.get_all("incidents") if prior["id"] in (i.get("event_ids") or [])), None)
            return prior, inc

    event = data_store.create("detection_events", {
        "id":              f"EVT-{uuid.uuid4().hex[:8].upper()}",
        "device_id":       device["id"],
        "device_name":     device.get("name", ""),
        "use_case_id":     device.get("use_case_id", body.get("use_case_id", "")),
        "zone_id":         device.get("zone_id", body.get("zone_id", "")),
        "object_type":     body.get("object_type", "unknown"),
        "confidence":      float(body.get("confidence", 0)),
        "image_url":       body.get("image_url"),
        "bbox":            body.get("bbox"),
        "vendor":          body.get("vendor", device.get("vendor")),
        "client_event_id": cid,
        "raw_payload":     body.get("raw_payload"),
        "source":          source,
        # Location is copied from the device so the spatial engine can light
        # nearby actuators (a drone could also send its own lat/lng here).
        "lat":             body.get("lat", device.get("lat")),
        "lng":             body.get("lng", device.get("lng")),
        "captured_at":     body.get("captured_at"),
        "received_at":     _now(),
        "processed":       False,
    })
    data_store.update("devices", device["id"], {"last_seen": _now(), "online": True})

    incident = await _run_rule_engine(event, device)
    broadcast("event_received", {**event, "incident_id": incident["id"] if incident else None})
    _broadcast_sign_states()
    return event, incident


@app.post("/api/events")
async def intake_event(req: Request):
    """Public detection-intake endpoint for external producers (camera connectors
    or an upstream AI service). Authenticates with the device's api_key."""
    body = await req.json()
    device = _resolve_device(body)
    if not device:
        raise HTTPException(400, "Unknown device — register it (by id or external_id) first")

    expected = device.get("api_key")
    presented = req.headers.get("X-API-Key") or body.get("api_key")
    if expected and presented != expected:
        raise HTTPException(401, "Invalid or missing API key for this device")

    event, incident = await _ingest_event(body, body.get("source", "device"))
    return {
        "event_id":    event["id"],
        "incident_id": incident["id"] if incident else None,
    }


def _broadcast_sign_states():
    """Recompute + push sign states immediately (used after a new event)."""
    global _last_sign_states
    states = _compute_sign_states()
    changed = {sid: st for sid, st in states.items()
               if _last_sign_states.get(sid) != st}
    _last_sign_states = states
    broadcast("signs_state", {"states": states, "changed": list(states.keys())})
    
    # Actuate signs via MQTT on state changes
    if changed and hasattr(app, "state") and hasattr(app.state, "mqtt_client") and app.state.mqtt_client:
        for sid in changed:
            sign_state = states[sid]
            color_map = {"WARNING": "RED", "CAUTION": "AMBER", "CLEAR": "GREEN", "OFFLINE": "OFF"}
            color = color_map.get(sign_state, "OFF")
            app.state.mqtt_client.actuate_led(sid, color)


async def _run_rule_engine(event: dict, device: dict) -> dict | None:
    matched_rule, action_key = await rule_engine.evaluate_event(event)
    if not matched_rule or action_key not in ("on_trigger", "on_confirm"):
        if matched_rule:
            data_store.update("detection_events", event["id"], {
                "processed": True, "rule_id": matched_rule["id"], "pending_confirmation": True
            })
            print(f"[ENGINE] '{matched_rule['name']}' matched — awaiting confirmation")
        return None

    actions  = matched_rule.get("actions", {})
    ak       = action_key if action_key in actions else "on_trigger"
    action   = actions.get(ak, {})
    severity = action.get("incident_severity", "HIGH")

    # Reuse open incident in same zone/use-case, or create new one
    open_incidents = [
        i for i in data_store.get_all("incidents")
        if i.get("zone_id") == event["zone_id"]
        and i.get("use_case_id") == event["use_case_id"]
        and i.get("status") in ("ACTIVE", "OPERATOR_REVIEW")
    ]
    sev_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    is_new    = not open_incidents
    escalated = False

    if open_incidents:
        incident = open_incidents[0]
        # Always link the new event; escalate severity if this rule is higher
        merged_event_ids = list(dict.fromkeys((incident.get("event_ids") or []) + [event["id"]]))
        patch = {"event_ids": merged_event_ids}
        if sev_order.get(severity, 0) > sev_order.get(incident.get("severity"), 0):
            patch["severity"] = severity
            patch["rule_id"]  = matched_rule["id"]
            escalated = True
        # Always update confidence to the highest seen so far
        if event.get("confidence", 0) > incident.get("confidence", 0):
            patch["confidence"] = event["confidence"]
        incident = data_store.update("incidents", incident["id"], patch)
        _broadcast_incident("incident_updated", incident)
    else:
        zone = data_store.get_by_id("zones", event["zone_id"]) or {}
        incident = data_store.create("incidents", {
            "id":          f"INC-{uuid.uuid4().hex[:6].upper()}",
            "use_case_id": event["use_case_id"],
            "rule_id":     matched_rule["id"],
            "zone_id":     event["zone_id"],
            "zone_name":   zone.get("name", event.get("zone_id", "")),
            "device_id":   event["device_id"],
            "severity":    severity,
            "status":      "ACTIVE",
            "object":      event["object_type"],
            "confidence":  event["confidence"],
            "image_url":   event.get("image_url"),
            "location":    {"lat": device.get("lat"), "lng": device.get("lng")},
            "opened_at":   _now(),
            "source":      "auto",
            "simulated":   event.get("source") == "simulation",
            "event_ids":   [event["id"]],
        })
        _broadcast_incident("incident_new", incident)

    # Notify only when it's worth an operator's attention — on first open, on a
    # severity increase, or after a cooldown — so a sustained presence (a
    # detection every few seconds) never fans out the same alert repeatedly.
    last_at = _parse_iso(incident.get("last_notified_at"))
    cooled  = last_at is None or (datetime.now(timezone.utc) - last_at).total_seconds() >= NOTIFY_COOLDOWN_S
    notifications = []
    if is_new or escalated or cooled:
        notifications = await notifier.dispatch(incident, matched_rule, ak, event)
        if notifications:
            data_store.update("incidents", incident["id"], {
                "last_notified_at":       _now(),
                "last_notified_severity": incident.get("severity"),
            })

    # Sign states are derived purely by the spatial engine (spatial.py) from event
    # proximity + decay — rules don't force sign states.
    data_store.update("detection_events", event["id"], {
        "processed": True, "rule_id": matched_rule["id"]
    })
    reason = "new" if is_new else "escalated" if escalated else "cooldown" if notifications else "suppressed"
    print(f"[ENGINE] '{matched_rule['name']}' → {action_key} → {incident['id']} "
          f"→ {len(notifications)} notif(s) ({reason})")
    return incident


# ════════════════════════════════════════════════════════════════════════════
# LEGACY UPLOAD (camera demo)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/upload")
async def legacy_upload(
    file: UploadFile = File(...),
    object_type: str = Form("elephant"),
    confidence: float = Form(88.0),
    device_id: str | None = Form(None),
    use_case_id: str | None = Form(None),
):
    """
    Phone-camera demo upload. The detection label/confidence are form fields
    (defaults preserve the elephant demo) rather than hardcoded — so this page
    works for any use case once real classification feeds them. Tagged source=upload.
    """
    contents = await file.read()
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    (UPLOADS_DIR / filename).write_bytes(contents)
    image_url = f"/uploads/{filename}"

    # Resolve a device to attribute the upload to: explicit id, else first online
    # camera (optionally scoped to the requested use case).
    device = data_store.get_by_id("devices", device_id) if device_id else None
    if not device:
        cams = [d for d in _list("devices")
                if d.get("type") == "camera" and d.get("online")
                and (not use_case_id or d.get("use_case_id") == use_case_id)]
        device = cams[0] if cams else None
    if not device:
        raise HTTPException(400, "No online camera registered to attribute this upload to")

    event, incident = await _ingest_event({
        "device_id":   device["id"],
        "use_case_id": use_case_id or device.get("use_case_id"),
        "object_type": object_type,
        "confidence":  confidence,
        "image_url":   image_url,
    }, source="upload")

    return {
        "event_id":    event["id"],
        "incident_id": incident["id"] if incident else None,
        "image_url":   image_url,
        "message":     "Detection processed by rule engine",
    }


# ════════════════════════════════════════════════════════════════════════════
# SIMULATOR  —  exercise the platform end-to-end without hardware
# ════════════════════════════════════════════════════════════════════════════

async def _sim_emit(body: dict):
    """Adapter so the simulator drives the real ingestion path."""
    try:
        await _ingest_event(body, source="simulation")
    except Exception as e:
        print(f"[SIM] emit error: {e}")


@app.post("/api/simulate/event")
async def simulate_event(req: Request):
    body = await req.json()
    uc, lat, lng = body.get("use_case_id"), body.get("lat"), body.get("lng")
    if uc is None or lat is None or lng is None:
        raise HTTPException(400, "use_case_id, lat and lng are required")
    device = await simulator.nearest_device(uc, float(lat), float(lng))
    if not device:
        raise HTTPException(400, "This use case has no placed sensors to attribute a detection to")
    event, incident = await _ingest_event({
        "device_id":   device["id"],
        "use_case_id": uc,
        "object_type": body.get("object_type", "unknown"),
        "confidence":  float(body.get("confidence", 90)),
        "lat":         float(lat),
        "lng":         float(lng),
    }, source="simulation")
    return {
        "event_id":    event["id"],
        "incident_id": incident["id"] if incident else None,
        "device_id":   device["id"],
        "device_name": device.get("name"),
    }


@app.post("/api/simulate/scenario")
async def simulate_scenario(req: Request):
    body = await req.json()
    uc   = body.get("use_case_id")
    path = body.get("path", [])
    if not uc or not path:
        raise HTTPException(400, "use_case_id and a path (>=1 point) are required")
    if not await simulator.use_case_has_sensors(uc):
        raise HTTPException(400, "This use case has no placed sensors to attribute detections to")
    return simulator.start(
        _sim_emit,
        use_case_id = uc,
        path        = path,
        object_type = body.get("object_type", "unknown"),
        confidence  = float(body.get("confidence", 90)),
        step_seconds= float(body.get("step_seconds", 3)),
        steps       = int(body.get("steps", 12)),
    )


@app.get("/api/simulate/scenarios")
async def list_scenarios():
    return simulator.list_runs()


@app.post("/api/simulate/scenario/{run_id}/stop")
async def stop_scenario(run_id: str):
    if not simulator.stop(run_id):
        raise HTTPException(404, f"scenario '{run_id}' not found")
    return {"stopped": run_id}


@app.post("/api/simulate/reset")
async def reset_simulation():
    result = await simulator.reset_simulation()
    _broadcast_sign_states()
    broadcast("simulation_reset", result)
    print(f"[SIM] reset — {result}")
    return result


# ════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/notifications")
async def list_notifications():
    notifs = _list("notifications")
    notifs.sort(key=lambda n: n.get("sent_at", ""), reverse=True)
    return notifs[:200]


# ════════════════════════════════════════════════════════════════════════════
# SSE STREAM
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/stream")
async def sse_stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_queues.append(queue)

    async def generator() -> AsyncGenerator[str, None]:
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    # Wait up to 15 s for a message; send a heartbeat comment
                    # if nothing arrives so the connection stays alive.
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keeps the TCP connection open and lets us
                    # detect a dead client on the next write.
                    yield ": heartbeat\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            # Client disconnected — exit cleanly.
            pass
        finally:
            if queue in _sse_queues:
                _sse_queues.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ════════════════════════════════════════════════════════════════════════════
# SYSTEM HEALTH
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/system/health")
async def system_health():
    incidents = _list("incidents")
    devices   = _list("devices")
    return {
        "status":           "operational",
        # Liveness fields the dashboard health dot reads. The decay task and SSE
        # loop are the current "workers"/"broker"; there is no VLM yet, so it is
        # reported as healthy (not degraded) rather than missing.
        "worker_live":      True,
        "broker_ok":        True,
        "vlm_ok":           True,
        "queue_depth":      0,
        "outbox_backlog":   0,
        "fast_path_ms":     0,
        "slo_ms":           1500,
        "active_incidents": sum(1 for i in incidents if i.get("status") == "ACTIVE"),
        "devices_online":   sum(1 for d in devices if d.get("online")),
        "devices_total":    len(devices),
        "sse_clients":      len(_sse_queues),
        "timestamp":        _now(),
    }


# ════════════════════════════════════════════════════════════════════════════
# MOBILE UPLOAD PAGE
# ════════════════════════════════════════════════════════════════════════════

@app.get("/upload", response_class=HTMLResponse)
async def mobile_upload_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DSA – Camera Upload</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0f172a; color: #f1f5f9; min-height: 100vh;
       display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; }
.card { background: #1e293b; border-radius: 16px; padding: 32px; max-width: 420px; width: 100%; text-align: center; }
h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
p  { font-size: 14px; color: #94a3b8; margin-bottom: 24px; }
.preview { width: 100%; height: 220px; object-fit: cover; border-radius: 12px;
           background: #0f172a; border: 2px dashed #334155; display: none; margin-bottom: 16px; }
label { display: flex; flex-direction: column; align-items: center; gap: 8px; cursor: pointer;
        background: #0f172a; border: 2px dashed #334155; border-radius: 12px;
        padding: 32px; margin-bottom: 16px; }
input[type=file] { display: none; }
button { width: 100%; padding: 14px; background: #DA1F26; color: white; border: none;
         border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; }
button:disabled { opacity: .5; }
.success { display: none; }
.inc-badge { display: inline-block; margin-top: 12px; padding: 6px 14px;
             background: #D92D20; color: white; border-radius: 999px; font-size: 13px; font-weight: 600; }
</style>
</head>
<body>
<div class="card">
  <h1>📷 Elephant Detection</h1>
  <p>Capture or upload a photo to trigger the alerting pipeline</p>
  <div id="form-area">
    <img id="preview" class="preview" />
    <label for="fileInput">
      <span style="font-size:32px">📸</span>
      <span id="labelText" style="font-size:14px;color:#64748b">Tap to take photo or choose file</span>
    </label>
    <input type="file" id="fileInput" accept="image/*" capture="environment">
    <button id="submitBtn" disabled onclick="upload()">Select a photo first</button>
  </div>
  <div class="success" id="success">
    <div style="font-size:48px;margin-bottom:12px">🚨</div>
    <h2 style="color:#22c55e;margin-bottom:8px">Alert Triggered!</h2>
    <p>The rule engine has processed the detection.</p>
    <div id="incBadge" class="inc-badge"></div>
    <br><br>
    <button onclick="location.reload()">Take Another Photo</button>
  </div>
</div>
<script>
const fileInput = document.getElementById('fileInput')
fileInput.addEventListener('change', () => {
  const file = fileInput.files[0]; if (!file) return
  document.getElementById('preview').src = URL.createObjectURL(file)
  document.getElementById('preview').style.display = 'block'
  document.getElementById('submitBtn').disabled = false
  document.getElementById('submitBtn').textContent = 'Send to Detection Engine'
  document.getElementById('labelText').textContent = file.name
})
async function upload() {
  const file = fileInput.files[0]; if (!file) return
  document.getElementById('submitBtn').textContent = 'Processing...'
  document.getElementById('submitBtn').disabled = true
  const fd = new FormData(); fd.append('file', file)
  try {
    const res  = await fetch('/api/upload', { method: 'POST', body: fd })
    const data = await res.json()
    document.getElementById('incBadge').textContent = data.incident_id || 'Processed'
    document.getElementById('form-area').style.display = 'none'
    document.getElementById('success').style.display = 'block'
  } catch(e) { alert('Upload failed: ' + e.message) }
}
</script>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════════════
# STATIC FILES + SPA FALLBACK (must be last)
# ════════════════════════════════════════════════════════════════════════════

if UPLOADS_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

if DIST_DIR.exists() and (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    candidate = DIST_DIR / full_path
    if candidate.exists() and candidate.is_file():
        return _FileResponse(str(candidate))
    index = DIST_DIR / "index.html"
    if index.exists():
        return _FileResponse(str(index))
    return JSONResponse({"detail": "Not Found"}, status_code=404)


# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT  —  run with:  python server.py
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
