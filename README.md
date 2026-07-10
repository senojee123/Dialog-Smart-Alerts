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
5. **Simulator** (`/simulator`): pick a use case, drop a single detection, or draw a path and
   play a **moving target** — watch the RED→AMBER→GREEN trail travel and incidents escalate.
   "Reset sim data" wipes simulated data only.
6. **Phone camera:** open `http://<your-ip>:8000/upload` on a phone on the same Wi-Fi
   (the backend prints the URL on startup), take a photo → triggers the pipeline.
7. **Setup Wizard** (`/setup`): build a brand-new (e.g. non-elephant) use case end-to-end, then
   hit **Run a test detection** in the Review step to watch it drive the engine before activating.

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

**Working & verified end-to-end:**
- General rule engine (single-trigger HIGH → dual-confirm CRITICAL escalation) with
  **no alert storms** (notify on open / escalation / cooldown only)
- Spatial radius + time-decay sign actuation (movement trail emerges automatically)
- **Design system "Elevated Dialog"** (`src/components/ui/`) + live reference at `/styleguide`
- **Scenario Simulator** (`/simulator`): single + moving-target detections through the real
  pipeline, with one-click reset — demo without hardware
- **Setup Wizard** (`/setup`) rebuilt — 5 steps: Scenario → Sensors → Signs → Response →
  Review & Test; **verified end-to-end for a non-elephant scenario** (it builds a use case
  that drives the engine, and self-tests in the Review step)
- Live Incidents (enriched schema, SSE), Devices/Road Signs on the live registry
- Full CRUD admin pages: Use Cases, Devices, Stakeholders, Rules, Sign Boards

**Architecture docs:** `docs/architecture.md` · `docs/simulation.md` · `docs/design-system.md`

**Next / pending (fast follow):**
- Real hardware / the middle ingestion layer POST to the same `/api/events` contract (`source` field)
- Local-only stubs not yet wired to backend: **Hardware Units**, **Escalation Policies**, **Templates**
- Admin screens still render via the CrudShell→`ui/` shim (functional; not yet fully redesigned)

---

## GitHub
Repo: https://github.com/Innovation-foundry/dialog-smart-alerts
