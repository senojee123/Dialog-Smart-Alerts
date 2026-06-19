# Dialog Smart Alerts

A general **Notification & Alerting Platform**. Phase-1 reference use case: **Elephant
Detection** on road corridors — cameras/sensors detect wildlife, a rule engine raises
incidents and notifies stakeholders, and nearby LED road-sign boards light up by
proximity (RED → AMBER → GREEN).

The platform is **use-case driven**: the elephant scenario is just seeded data that
configures a general engine (devices → detections → rules → incidents → notifications +
spatial sign actuation).

---

## Stack
- **Frontend:** React 18 + Vite 5 + Tailwind 3 + React Router 6 + Leaflet + lucide-react
- **Backend:** Python FastAPI + uvicorn (JSON file storage, no database needed)
- **Live updates:** Server-Sent Events (SSE)

---

## Prerequisites (new machine)
1. **Node.js** LTS (18+) — includes npm → https://nodejs.org
2. **Python** 3.10+ → https://python.org
3. **git**

Verify:
```bash
node -v && npm -v && python --version && git --version
```

---

## Setup
```bash
git clone https://github.com/Innovation-foundry/dialog-smart-alerts.git
cd dialog-smart-alerts

# Frontend deps
npm install

# Backend deps
cd backend
pip install -r requirements.txt
cd ..
```

---

## Running

### Option A — Dev mode (recommended; hot reload) ⭐
Two terminals:

```bash
# Terminal 1 — backend API on :8000
cd backend
python server.py
```
```bash
# Terminal 2 — frontend dev server on :5173 (proxies /api, /uploads, /upload to :8000)
npm run dev
```
Open **http://localhost:5173**. Edit any `src/` file → instant reload. No build needed.

### Option B — Production-like (single server)
Build the SPA once, then the Python backend serves it on :8000:
```bash
npm run build          # produces dist/
cd backend
python server.py       # serves dist/ + API on http://localhost:8000
```

> On the old (no-npm) laptop we built `dist/` via GitHub Actions and downloaded it.
> With npm available now, just run `npm run build` (or skip it entirely and use dev mode).

---

## Demo flow
1. Start the app (Option A or B).
2. On first run the backend **auto-seeds** the Elephant Detection use case
   (3 sensors, 11 LED boards along the B43 corridor, 4 stakeholders, 2 rules).
3. **Road Signs → Map → Simulate detection** → click the corridor → nearby boards
   light RED, then fade AMBER → GREEN.
4. Two detections in the same zone escalate the incident to **CRITICAL** and fan out
   notifications (logged in the backend terminal).
5. **Phone camera:** open `http://<your-ip>:8000/upload` on a phone on the same Wi-Fi
   (the backend prints the URL on startup), take an elephant photo → triggers the pipeline.
6. **Setup Wizard** (`/setup`): build a brand-new use case end-to-end.

To reset all runtime data: delete `backend/data/` and restart (it re-seeds).

---

## Project structure
```
backend/
  server.py        FastAPI app: CRUD APIs, /api/events intake, SSE, SPA serving
  data_store.py    generic JSON CRUD (writes to backend/data/, gitignored)
  rule_engine.py   condition matching + confirmation-window evaluation
  spatial.py       radius + time-decay sign-state engine (haversine)
  notifier.py      simulated SMS/WhatsApp/Email dispatch
  seed.py          Elephant Detection seed data (runs once when data/ empty)
  requirements.txt
src/
  pages/           LiveIncidents, MapView, RoadSigns, Devices, HardwareUnits,
                   SetupWizard, admin/{UseCases,Rules,Stakeholders,Devices,RoadSignBoards,...}
  components/      shell/, incidents/, roadsigns/, map/, admin/CrudShell, wizard/
  hooks/           useApi (generic CRUD), useIncidents, useIncidentStream, useSystemHealth
.github/workflows/ build.yml  (legacy CI build of dist/ — optional now)
```

---

## Status (handoff)

**Working & verified end-to-end (via HTTP):**
- General rule engine (single-trigger HIGH → dual-confirm CRITICAL escalation)
- Spatial radius + time-decay sign actuation (movement trail emerges automatically)
- Full CRUD admin pages: Use Cases, Devices, Stakeholders, Rules, Sign Boards
- Live Incidents page wired to backend (enriched incident schema, live SSE, persisted close)
- Ops Devices page on live registry
- **Setup Wizard** (`/setup`) — 6 steps: Use Case → Inputs → Outputs → Spatial → Notifications → Review

**Next / pending:**
- Smoke-test the Setup Wizard's full API sequence on the new machine (was about to verify
  when the laptop switch happened) — run dev mode, walk all 6 steps, confirm a wizard-built
  use case drives the engine (simulate a detection on its devices).
- Low-priority stubs not yet wired to backend: **Hardware Units**, **Escalation Policies**,
  **Templates** pages.

---

## GitHub
Repo: https://github.com/Innovation-foundry/dialog-smart-alerts
