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
import data_store
import rule_engine
import notifier
import spatial

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
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
    seed.run()
    _print_local_ip()
    task = asyncio.create_task(_decay_tick())
    yield
    task.cancel()


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
    device = _create("devices", body)
    broadcast("device_created", device)
    return device

@app.get("/api/devices/{id}")
async def get_device(id: str):
    return _get("devices", id)

@app.put("/api/devices/{id}")
async def update_device(id: str, req: Request):
    device = _update("devices", id, await req.json())
    broadcast("device_updated", device)
    return device

@app.delete("/api/devices/{id}")
async def delete_device(id: str):
    return _delete("devices", id)


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

@app.get("/api/incidents")
async def list_incidents():
    incidents = _list("incidents")
    incidents.sort(key=lambda i: i.get("opened_at", ""), reverse=True)
    return incidents

@app.post("/api/incidents")
async def create_incident_manual(req: Request):
    body = await req.json()
    body.setdefault("opened_at", _now())
    body.setdefault("status", "ACTIVE")
    body.setdefault("source", "manual")
    incident = _create("incidents", body)
    broadcast("incident_new", incident)
    return incident

@app.get("/api/incidents/{id}")
async def get_incident(id: str):
    return _get("incidents", id)

@app.put("/api/incidents/{id}")
async def update_incident(id: str, req: Request):
    body = await req.json()
    incident = _update("incidents", id, body)
    broadcast("incident_updated", incident)
    return incident

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


@app.post("/api/events")
async def intake_event(req: Request):
    body = await req.json()

    device = data_store.get_by_id("devices", body.get("device_id", ""))
    if not device:
        raise HTTPException(400, "Unknown device_id — register device first")

    event = data_store.create("detection_events", {
        "id":          f"EVT-{uuid.uuid4().hex[:8].upper()}",
        "device_id":   device["id"],
        "device_name": device.get("name", ""),
        "use_case_id": device.get("use_case_id", body.get("use_case_id", "")),
        "zone_id":     device.get("zone_id", body.get("zone_id", "")),
        "object_type": body.get("object_type", "unknown"),
        "confidence":  float(body.get("confidence", 0)),
        "image_url":   body.get("image_url"),
        "raw_payload": body.get("raw_payload"),
        # Location is copied from the device so the spatial engine can light
        # nearby actuators (a drone could also send its own lat/lng here).
        "lat":         body.get("lat", device.get("lat")),
        "lng":         body.get("lng", device.get("lng")),
        "received_at": _now(),
        "processed":   False,
    })
    data_store.update("devices", device["id"], {"last_seen": _now(), "online": True})

    incident = _run_rule_engine(event, device)
    broadcast("event_received", {**event, "incident_id": incident["id"] if incident else None})
    _broadcast_sign_states()

    return {
        "event_id":    event["id"],
        "incident_id": incident["id"] if incident else None,
    }


def _broadcast_sign_states():
    """Recompute + push sign states immediately (used after a new event)."""
    global _last_sign_states
    states = _compute_sign_states()
    _last_sign_states = states
    broadcast("signs_state", {"states": states, "changed": list(states.keys())})


def _run_rule_engine(event: dict, device: dict) -> dict | None:
    matched_rule, action_key = rule_engine.evaluate_event(event)
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

    if open_incidents:
        incident = open_incidents[0]
        if sev_order.get(severity, 0) > sev_order.get(incident.get("severity"), 0):
            incident = data_store.update("incidents", incident["id"], {
                "severity": severity, "rule_id": matched_rule["id"]
            })
            broadcast("incident_updated", incident)
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
            "event_ids":   [event["id"]],
        })
        broadcast("incident_new", incident)

    notifications = notifier.dispatch(incident, matched_rule, ak, event)
    actuated = notifier.actuate_signs(matched_rule, ak)
    if actuated:
        broadcast("signs_updated", {"sign_ids": actuated, "state": action.get("sign_state")})

    data_store.update("detection_events", event["id"], {
        "processed": True, "rule_id": matched_rule["id"]
    })
    print(f"[ENGINE] '{matched_rule['name']}' → {action_key} → incident {incident['id']} → {len(notifications)} notif(s)")
    return incident


# ════════════════════════════════════════════════════════════════════════════
# LEGACY UPLOAD (camera demo)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/upload")
async def legacy_upload(file: UploadFile = File(...)):
    contents = await file.read()
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    (UPLOADS_DIR / filename).write_bytes(contents)
    image_url = f"/uploads/{filename}"

    devices = [d for d in _list("devices") if d.get("type") == "camera" and d.get("online")]
    device = devices[0] if devices else data_store.get_by_id("devices", "DEV-001") or {}
    device_id = device.get("id", "DEV-001")

    event = data_store.create("detection_events", {
        "id":          f"EVT-{uuid.uuid4().hex[:8].upper()}",
        "device_id":   device_id,
        "device_name": device.get("name", ""),
        "use_case_id": device.get("use_case_id", "UC-001"),
        "zone_id":     device.get("zone_id", "ZONE-B43"),
        "object_type": "elephant",
        "confidence":  88.0,
        "image_url":   image_url,
        "lat":         device.get("lat"),
        "lng":         device.get("lng"),
        "received_at": _now(),
        "processed":   False,
    })
    data_store.update("devices", device_id, {"last_seen": _now(), "online": True})
    incident = _run_rule_engine(event, device)
    broadcast("event_received", {**event, "incident_id": incident["id"] if incident else None})
    _broadcast_sign_states()

    return {
        "event_id":    event["id"],
        "incident_id": incident["id"] if incident else None,
        "image_url":   image_url,
        "message":     "Elephant detection processed by rule engine",
    }


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
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
