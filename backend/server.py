import asyncio
import json
import uuid
import random
import socket
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# ── directories ──────────────────────────────────────────────────────────────
DIST_DIR    = Path(__file__).parent.parent / "dist"
UPLOAD_DIR  = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ── in-memory store ───────────────────────────────────────────────────────────
def ts(offset_minutes=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)).isoformat()

INCIDENTS: List[dict] = [
    {
        "incident_id": "INC-SEED-0001",
        "severity": "HIGH",
        "status": "ACTIVE",
        "opened_at": ts(18),
        "updated_at": ts(12),
        "object": "leopard",
        "herd_size": 1,
        "location": {"lat": 6.8500, "lng": 79.7900, "description": "Village buffer zone, Palatupana"},
        "zone": "Yala South",
        "ai_confirmed": True,
        "ai_summary": "Single leopard detected near village boundary fence.",
        "confidence": 0.88,
        "risk_factors": ["village_proximity"],
        "distance_to_road_m": 340,
        "is_night": True,
        "detections_in_zone": 2,
        "incident_media": None,
        "rules_triggered": [{"name": "Village Buffer Alert", "severity": "HIGH"}],
        "stakeholders": [
            {"id": "s1", "name": "Priya Wijesinghe", "role": "Village Officer",
             "channels": [{"type": "sms", "status": "delivered", "ack": "RECEIVED"}]}
        ],
        "hardware": {"unit_id": "HW-003", "name": "Siren Unit C", "state": "OFF", "expires_at": None},
        "timeline": [
            {"ts": ts(18), "event": "Incident opened — detection by camera CAM-012"},
            {"ts": ts(17), "event": "AI confirmed — confidence 0.88"},
            {"ts": ts(16), "event": "SMS sent to Priya Wijesinghe"},
            {"ts": ts(12), "event": "Priya Wijesinghe acknowledged via SMS"},
        ],
        "operator_notes": "",
    },
    {
        "incident_id": "INC-SEED-0002",
        "severity": "LOW",
        "status": "RESOLVED",
        "opened_at": ts(120),
        "updated_at": ts(100),
        "object": "deer",
        "herd_size": 2,
        "location": {"lat": 6.9400, "lng": 79.8800, "description": "Eastern trail, Block 2"},
        "zone": "Yala East",
        "ai_confirmed": True,
        "ai_summary": "Two spotted deer near water source. No threat.",
        "confidence": 0.97,
        "risk_factors": [],
        "distance_to_road_m": 1200,
        "is_night": False,
        "detections_in_zone": 3,
        "incident_media": None,
        "rules_triggered": [{"name": "Wildlife Activity Log", "severity": "LOW"}],
        "stakeholders": [],
        "hardware": {"unit_id": None, "name": None, "state": None, "expires_at": None},
        "timeline": [
            {"ts": ts(120), "event": "Incident opened"},
            {"ts": ts(119), "event": "AI confirmed — confidence 0.97"},
            {"ts": ts(100), "event": "Incident auto-resolved"},
        ],
        "operator_notes": "",
    },
]

NOTIFICATIONS: List[dict] = []
SSE_CLIENTS:   List[asyncio.Queue] = []

# ── helpers ───────────────────────────────────────────────────────────────────
async def broadcast(event: dict):
    for q in list(SSE_CLIENTS):
        await q.put(event)


def simulate_sms(incident_id: str, contact: str, phone: str) -> dict:
    return {
        "ts":      ts(),
        "type":    "sms",
        "to":      f"{contact} ({phone})",
        "message": f"⚠️ CRITICAL: Elephant detected. Incident {incident_id}. Respond immediately.",
        "status":  "simulated",
    }


# ── API routes ────────────────────────────────────────────────────────────────
@app.get("/api/incidents")
async def get_incidents():
    return INCIDENTS


@app.get("/api/notifications")
async def get_notifications():
    return NOTIFICATIONS


@app.get("/api/stream/incidents")
async def stream_incidents():
    queue: asyncio.Queue = asyncio.Queue()
    SSE_CLIENTS.append(queue)

    async def generator():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            if queue in SSE_CLIENTS:
                SSE_CLIENTS.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/incidents/{incident_id}/close")
async def close_incident(incident_id: str):
    for inc in INCIDENTS:
        if inc["incident_id"] == incident_id:
            inc["status"] = "CLOSED"
            inc["updated_at"] = ts()
            inc["timeline"].append({"ts": ts(), "event": "Incident closed by operator"})
            await broadcast(inc)
            return {"ok": True}
    return {"ok": False, "error": "not found"}


@app.post("/api/hardware/{unit_id}/override")
async def hardware_override(unit_id: str, body: dict):
    state = body.get("state", "OFF")
    for inc in INCIDENTS:
        if inc.get("hardware", {}).get("unit_id") == unit_id:
            inc["hardware"]["state"] = state
            inc["updated_at"] = ts()
            inc["timeline"].append({"ts": ts(), "event": f"Hardware {unit_id} manually set to {state} by operator"})
            await broadcast(inc)
    return {"ok": True}


@app.get("/upload", response_class=HTMLResponse)
async def upload_page():
    return UPLOAD_PAGE_HTML


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    # Save image
    ext        = Path(file.filename).suffix or ".jpg"
    filename   = f"{uuid.uuid4().hex}{ext}"
    dest       = UPLOAD_DIR / filename
    content    = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    # Simulate AI processing delay
    await asyncio.sleep(1.8)

    incident_id = f"INC-LIVE-{uuid.uuid4().hex[:6].upper()}"
    herd        = random.randint(1, 3)
    conf        = round(random.uniform(0.87, 0.97), 2)
    now         = ts()

    incident = {
        "incident_id":      incident_id,
        "severity":         "CRITICAL",
        "status":           "ACTIVE",
        "opened_at":        now,
        "updated_at":       now,
        "object":           "elephant",
        "herd_size":        herd,
        "location":         {"lat": 6.9271 + random.uniform(-0.05, 0.05),
                             "lng": 79.8612 + random.uniform(-0.05, 0.05),
                             "description": "Live camera upload — field detection"},
        "zone":             "Live Detection Zone",
        "ai_confirmed":     True,
        "ai_summary":       (
            f"{herd} elephant{'s' if herd > 1 else ''} detected via field camera. "
            f"Thermal + RGB fusion analysis confirmed presence with {int(conf*100)}% confidence. "
            "Road crossing risk assessed — immediate response recommended."
        ),
        "confidence":       conf,
        "risk_factors":     ["road_proximity", "herd" if herd > 1 else "night_movement"],
        "distance_to_road_m": random.randint(15, 80),
        "is_night":         False,
        "detections_in_zone": 1,
        "incident_media":   f"/uploads/{filename}",
        "rules_triggered":  [{"name": "Road Proximity Alert", "severity": "CRITICAL"}],
        "stakeholders": [
            {
                "id": "live-duty",
                "name": "Duty Officer",
                "role": "On-call Field",
                "channels": [
                    {"type": "sms",  "status": "delivered", "ack": None},
                    {"type": "push", "status": "delivered", "ack": None},
                ],
            },
            {
                "id": "live-dwc",
                "name": "DWC Control Room",
                "role": "DWC Officer",
                "channels": [
                    {"type": "sms",   "status": "delivered", "ack": None},
                    {"type": "email", "status": "dispatched", "ack": None},
                ],
            },
        ],
        "hardware": {
            "unit_id":    "HW-001",
            "name":       "Siren Unit A",
            "state":      "ON",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        },
        "timeline": [
            {"ts": now, "event": "Incident opened — field camera upload"},
            {"ts": now, "event": f"AI confirmed — {int(conf*100)}% confidence, {herd} elephant(s)"},
            {"ts": now, "event": "Stakeholders notified — SMS sent to Duty Officer + DWC Control Room"},
            {"ts": now, "event": "Hardware unit HW-001 (Siren Unit A) activated automatically"},
        ],
        "operator_notes": "",
    }

    INCIDENTS.insert(0, incident)

    # Simulate SMS notifications
    NOTIFICATIONS.append(simulate_sms(incident_id, "Duty Officer", "+94 77X XXX XXXX"))
    NOTIFICATIONS.append(simulate_sms(incident_id, "DWC Control Room", "+94 11X XXX XXXX"))

    # Push to all SSE clients
    await broadcast(incident)

    return {"incident_id": incident_id, "ok": True}


# ── upload page HTML (served to phone) ───────────────────────────────────────
UPLOAD_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0"/>
  <title>DSA Field Camera</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, sans-serif; background: #1a1a1a; color: #fff; min-height: 100vh; display: flex; flex-direction: column; }
    header { background: #7B1E28; padding: 16px 20px; display: flex; align-items: center; gap: 12px; }
    .logo { width: 32px; height: 32px; background: #DA1F26; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; }
    header span { font-weight: 600; font-size: 15px; }
    .badge { margin-left: auto; background: #DA1F26; color: white; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 99px; letter-spacing: 1px; }
    main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; gap: 24px; }
    .card { background: #2a2a2a; border-radius: 16px; padding: 24px; width: 100%; max-width: 360px; }
    .card h2 { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
    .card p  { font-size: 13px; color: #aaa; margin-bottom: 20px; line-height: 1.5; }
    #preview { width: 100%; border-radius: 12px; display: none; margin-bottom: 16px; max-height: 260px; object-fit: cover; }
    .camera-btn { display: block; width: 100%; padding: 16px; background: #DA1F26; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; text-align: center; }
    .camera-btn:active { background: #B81A20; }
    #camera-input { display: none; }
    .submit-btn { display: none; width: 100%; padding: 16px; background: #12B76A; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 12px; }
    .submit-btn:active { background: #0e9656; }
    .state { text-align: center; padding: 20px; display: none; }
    .state.show { display: block; }
    .spinner { width: 40px; height: 40px; border: 3px solid #444; border-top-color: #DA1F26; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .success-icon { font-size: 48px; margin-bottom: 12px; }
    .incident-id { background: #DA1F26; color: white; padding: 6px 14px; border-radius: 8px; font-family: monospace; font-size: 14px; font-weight: 700; display: inline-block; margin: 8px 0; }
    .again-btn { margin-top: 16px; padding: 12px 24px; background: #333; color: white; border: none; border-radius: 10px; font-size: 14px; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <div class="logo">D</div>
    <span>Dialog Smart Alerts</span>
    <span class="badge">LIVE</span>
  </header>

  <main>
    <div class="card" id="upload-card">
      <h2>Field Camera Upload</h2>
      <p>Point your camera at a wildlife detection. The AI will analyse the image and raise an alert automatically.</p>

      <img id="preview" src="" alt="Preview"/>
      <button class="camera-btn" onclick="document.getElementById('camera-input').click()">
        📷 &nbsp; Capture / Select Image
      </button>
      <input type="file" id="camera-input" accept="image/*" capture="environment"/>
      <button class="submit-btn" id="submit-btn" onclick="submitImage()">
        ⚡ &nbsp; Submit Detection
      </button>
    </div>

    <div class="state" id="loading-state">
      <div class="spinner"></div>
      <p style="color:#aaa;font-size:14px">Analysing image…<br/>AI processing in progress</p>
    </div>

    <div class="state" id="success-state">
      <div class="success-icon">🚨</div>
      <p style="font-size:15px;font-weight:600;margin-bottom:4px">Incident Raised</p>
      <p style="color:#aaa;font-size:13px;margin-bottom:8px">AI confirmed detection. Stakeholders notified.</p>
      <div class="incident-id" id="result-id">—</div>
      <p style="color:#aaa;font-size:12px;margin-top:8px">Check the dashboard to see the live alert.</p>
      <button class="again-btn" onclick="reset()">Submit another</button>
    </div>
  </main>

  <script>
    let selectedFile = null;

    document.getElementById('camera-input').addEventListener('change', function(e) {
      selectedFile = e.target.files[0];
      if (!selectedFile) return;
      const reader = new FileReader();
      reader.onload = ev => {
        const img = document.getElementById('preview');
        img.src = ev.target.result;
        img.style.display = 'block';
        document.getElementById('submit-btn').style.display = 'block';
      };
      reader.readAsDataURL(selectedFile);
    });

    async function submitImage() {
      if (!selectedFile) return;
      document.getElementById('upload-card').style.display = 'none';
      document.getElementById('loading-state').classList.add('show');

      const form = new FormData();
      form.append('file', selectedFile);

      try {
        const res  = await fetch('/api/upload', { method: 'POST', body: form });
        const data = await res.json();
        document.getElementById('loading-state').classList.remove('show');
        document.getElementById('result-id').textContent = data.incident_id;
        document.getElementById('success-state').classList.add('show');
      } catch(err) {
        document.getElementById('loading-state').classList.remove('show');
        alert('Upload failed: ' + err.message);
        reset();
      }
    }

    function reset() {
      selectedFile = null;
      document.getElementById('preview').style.display = 'none';
      document.getElementById('preview').src = '';
      document.getElementById('submit-btn').style.display = 'none';
      document.getElementById('upload-card').style.display = 'block';
      document.getElementById('success-state').classList.remove('show');
      document.getElementById('camera-input').value = '';
    }
  </script>
</body>
</html>"""


# ── static files (must be last) ───────────────────────────────────────────────
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")


# ── startup banner ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"

    print("\n" + "="*55)
    print("  Dialog Smart Alerts — Demo Server")
    print("="*55)
    print(f"  Dashboard : http://localhost:8000")
    print(f"  Phone URL : http://{local_ip}:8000/upload")
    print("="*55)
    print("  Make sure your phone is on the same WiFi network.")
    print("="*55 + "\n")

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
