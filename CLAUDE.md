# CLAUDE.md — project context for Claude Code

Dialog Smart Alerts — a general Notification & Alerting Platform. Phase-1 use case:
elephant detection on roads. See **README.md** for full setup, run, and status.

## Run
- Dev (hot reload): terminal 1 `cd backend && python server.py` (:8000), terminal 2 `npm run dev` (:5173). Vite proxies `/api`, `/uploads`, `/upload` to :8000.
- Prod-like: `npm run build` then `cd backend && python server.py` serves `dist/` + API on :8000.
- Reset data: delete `backend/data/` (it re-seeds the elephant use case on startup).

## Architecture principle
The platform is **use-case driven** — the elephant scenario is seeded data, not hardcoded logic.
- **Rules** (`rule_engine.py`) decide incidents + notifications. Precedence: a confirmed rule > an immediate rule > a pending-confirmation rule (so a dual-confirm rule never blocks the single-detection alert).
- **Spatial** (`spatial.py`) decides LED sign states independently, by radius + time-decay: detection within `propagation_radius_m` → WARNING (RED) for `red_hold_s`, fades to CAUTION (AMBER) until `amber_hold_s`, then CLEAR (GREEN). Movement makes the lit zone travel — no per-target tracking.
- Detection events carry `lat/lng` (copied from the device) so spatial can locate them.
- Incidents are stored minimally but the API **enriches** them (`_enrich_incident`) into the shape the dashboard reads (`incident_id`, `zone`, `confidence` 0–1, `timeline`, `stakeholders`, etc.). SSE frames are `{type, data}`; the client forwards only `incident_new`/`incident_updated`.

## Conventions & gotchas
- **lucide-react is pinned at 0.400.0** — many icon names DON'T exist and render `<undefined/>` which white-screens the page. Confirmed missing: `MonitorDot`, `TriangleAlert`, `LayoutGrid`, `Grid`; `CheckCircle2` is risky (use `CheckCircle`). Verify any new icon import.
- Every route is wrapped in `ErrorBoundary` so a crash shows the error in-UI instead of a blank screen.
- Backend forces UTF-8 stdout (Windows cp1252 would crash on `→` in logs). `python server.py` has a `__main__` launcher.
- Storage is JSON files via `data_store.py` (generic CRUD). `backend/data/`, `backend/uploads/`, `__pycache__/` are gitignored.
- Frontend CRUD goes through `useApi(endpoint)`; admin pages share `components/admin/CrudShell.jsx`.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- History note: the old dev laptop had no npm, so `dist/` was built by GitHub Actions and downloaded. With npm now, build locally (`.github/workflows/build.yml` is optional).

## Current status / next step
Setup Wizard (`/setup`, 6 steps) is built but its full API sequence was **not yet smoke-tested**
(laptop switch interrupted it). Next: run dev mode, walk all 6 steps, confirm a wizard-built
use case drives the engine (simulate a detection on its new devices → boards light, incident fires).
Low-priority stubs still on local-only state: Hardware Units, Escalation Policies, Templates.
