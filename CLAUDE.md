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

## Design system, simulation & ingestion (added)
- **Design system "Elevated Dialog"** lives in `src/components/ui/` (single token source =
  `tailwind.config.js`). Import from `components/ui`. Live reference at route **`/styleguide`**.
  `components/admin/CrudShell.jsx` + the `components/common/{ConfirmDialog,SeverityChip,StatusBadge,Toast}`
  are now thin **re-export shims** over `ui/` — don't add logic there.
- **Ingestion boundary:** every detection enters via `_ingest_event(body, source)` in `server.py`
  (`POST /api/events`). Events carry `source` = `device|upload|simulation|ingestion`. Real cameras /
  the future middle layer POST the same contract — nothing downstream changes. The public endpoint
  **authenticates producers** with the device `api_key` (`X-API-Key`), resolves devices by `device_id`
  **or** `external_id` (MAC/serial), and de-dups by `client_event_id`. **The platform does NO inference**
  — inputs (edge cameras / an upstream AI service) send finished detections. Cross-team spec:
  `docs/integration-contract.md`; pipeline: `docs/architecture.md`.
- **Simulator** (`/simulator`, `backend/simulator.py`, `/api/simulate/*`): use-case-aware single
  events + moving-target scenario runs, all `source="simulation"`, with a one-click reset. The wizard's
  Review step reuses the injector as "Run a test detection". See `docs/simulation.md`.
- **No more elephant hardcoding:** `/api/upload`, the Road Signs "Simulate", and `RoadSignCard`
  labels are all object/use-case driven now (upload keeps an elephant *default* only).
- **Engine precision:** notifications only fire on open / escalation / after `NOTIFY_COOLDOWN_S`
  (no storms); confirmation ignores events consumed by closed incidents; `/api/system/health`
  returns liveness fields so the top-bar dot is green when healthy.

## Current status / next step
Setup Wizard rebuilt (`/setup`, 5 steps: Scenario → Sensors → Signs → Response → Review&Test),
verified end-to-end for a **non-elephant** scenario via API replay (boards light, incident opens).
Still local-only stubs (fast follow): Hardware Units, Escalation Policies, Templates; admin screens
still on the CrudShell shim (work, not yet redesigned). Docs in `docs/`.
