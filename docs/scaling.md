# Scaling plan — re-platforming for production load

**Targets:** millions of detection requests/day · 1000s of incidents/day · 100s of
devices · zero user-visible dashboard slowdown.
**Decisions:** PostgreSQL · design scale-out, run single-node first (Redis-ready) ·
staged migration (each stage independently reviewable).

The *architecture* (clean `/api/events` ingestion boundary, use-case-driven engine,
SSE delta model, the producer contract) already scales conceptually. What must be
re-platformed is the **persistence + execution model**, which is currently a
prototype.

## Why the current build won't hold the load

| Bottleneck | Where | Effect at scale |
|---|---|---|
| JSON-file store: full read + **full rewrite per op** | `data_store.py` | events file grows unbounded, rewritten on every detection → collapses |
| Synchronous file I/O in async handlers | every endpoint | blocks the event loop → no real concurrency |
| No locking / atomic writes | `data_store.py` | concurrent device writes corrupt/lose data |
| `_enrich_incident` re-reads all events+notifs **per incident** | `server.py` | listing N incidents = N×full-scans |
| Spatial recompute scans **all** events every few seconds | `spatial.py` + polling | O(events×signs) repeatedly |
| In-memory single-process SSE | `_sse_queues` | can't scale past one worker |
| Synchronous notification dispatch | `notifier.py` | a slow SMS provider blocks ingestion |

## Principles

- **Don't touch engine semantics.** Rules/spatial/notification *logic* stays; we
  change storage, queries, and the execution model.
- **Bounded queries, never full scans.** Every hot path filters by indexed columns
  and a time window.
- **Decouple intake from processing.** `/api/events` returns in ms; heavy work runs
  in a worker.
- **Redis-ready from day one**, single-node now: in-process today, multi-worker later
  is a config change.

---

## Stages

### B1 — PostgreSQL + async repository *(foundation; do first)*
- SQLAlchemy 2.0 **async** (asyncpg) + **Alembic** migrations; local PG via Docker.
- Tables: use_cases, zones, devices, road_signs, stakeholders, rules,
  detection_events, incidents, notifications. **JSONB** for flexible bits (spatial
  config, rule conditions/actions, channels, raw_payload, bbox).
- Replace `data_store.py` with an async **repository**; keep `rule_engine.py` /
  `spatial.py` **pure** (operate on data passed in, not global loads).
- Indexes: `detection_events(use_case_id, zone_id, received_at desc)`,
  `detection_events(client_event_id) unique`, `incidents(status, use_case_id, opened_at desc)`,
  `notifications(incident_id)`, `devices(external_id) unique`.
- Convert `seed.py` to idempotent inserts.

### B2 — Bounded queries (kill the full scans)
- **Confirmation:** query recent matching events by `(use_case_id, zone_id, received_at > cutoff)` — not all events.
- **Spatial:** only events in the last `amber_hold_s` window; cache per-zone state.
- **Enrichment:** batch-fetch events/notifs for a *page* of incident_ids in 2 queries, not N full scans.
- **Retention:** time-partition `detection_events` (monthly) + an archive/drop job so the hot table stays small.

### B3 — Dashboard read path: pagination + windowing
- `GET /api/incidents?status=ACTIVE&limit=&cursor=` — cursor pagination; default to the active/recent window, not all history.
- `useIncidents` holds the active window + lazy-loads history; stop loading everything into memory.
- Replace Road Signs / Devices **polling** with **SSE push** (sign-state deltas already broadcast).

### B4 — Intake throughput: fast-path + async processing
- `POST /api/events`: validate + auth + persist + **enqueue**, return `202 {event_id}` fast.
- Worker consumes the queue → runs rules/spatial/notify → broadcasts. Absorbs bursts; gives a real fast-path latency SLO.
- Queue on **Redis** (streams), worker in-process now → separate process when scaling out.

### B5 — SSE fan-out + notification outbox (Redis)
- SSE broadcast via **Redis pub/sub** so any worker/instance publishes and all clients receive.
- **Outbox pattern** for notifications: persist as `pending` → dispatcher worker sends with retries/backoff → updates `dispatched|delivered|failed`. Decouples providers *and* makes the delivery-state UI real.

### B6 — Ops hardening
- Connection pooling; **real** health checks (DB/Redis/worker liveness → the health dot reflects truth); metrics (queue depth, intake latency, processing lag) feeding the system-health panel; rate limiting on intake; graceful shutdown.

---

## Migration approach
Run the new data layer **alongside** the JSON store behind the repository interface,
backfill, then cut over — so each stage ships without a big-bang rewrite. Producers
and the dashboard contracts don't change.

## What stays the same
The producer contract (`docs/integration-contract.md`), the `_ingest_event`
boundary, the rule/spatial/notification *behaviour*, and the design system. This is
an internals re-platform, not a redesign.
