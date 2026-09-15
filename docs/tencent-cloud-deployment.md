# Hosting on Tencent Cloud

This maps the **actual** codebase — one FastAPI monolith (`backend/server.py`), a
Vite-built SPA (`dist/`), JSON-file storage with Postgres scaffolding already in
place (`db.py`/`models.py`, driver picked by `DATABASE_URL`), a background MQTT
client (`mqtt_client.py`), and a live SMS integration (`notifier.py` → Ideabiz) —
onto Tencent Cloud services. It gives two tiers: an **MVP** that fixes the
prototype's worst risks at low cost/complexity, and a **scale-out** tier that is a
1:1 lift of the stages already planned in [`scaling.md`](scaling.md) onto
Tencent-native services. Don't jump straight to the scale-out tier — graduate a
stage at a time as load actually demands it, same principle as `scaling.md`.

## What's actually being hosted

| Component | Today, in code | File |
|---|---|---|
| SPA | Built by Vite, served as static files | `dist/` (built), `vite.config.js` |
| API + SSE + SPA serving | One FastAPI process, one origin | `backend/server.py` |
| Data | JSON files, full-rewrite per write, no locking | `backend/data_store.py` → `backend/data/*.json` |
| DB scaffolding (unused by the app yet) | SQLAlchemy async, `DATABASE_URL` switches sqlite↔postgres | `backend/db.py`, `backend/models.py` |
| Uploaded evidence photos | Local disk | `backend/uploads/` |
| Device ingress | Outbound-only client, backend connects **out** to a **public** broker (`broker.hivemq.com`), subscribes to alert/status/heartbeat topics, publishes actuator commands | `backend/mqtt_client.py`, `.env.example` |
| HTTP device/simulator ingress | `POST /api/events`, `X-API-Key` auth, dedup by `client_event_id` | `server.py` `_ingest_event` |
| Phone-camera demo ingress | `POST /upload`, multipart | `server.py` |
| SMS dispatch | Real HTTPS calls to Ideabiz (LK SMS aggregator) | `backend/notifier.py` |
| Live dashboard updates | In-process SSE, single-worker only | `server.py` `_sse_queues` |

Current deploy artifacts in the repo (`Procfile`, the Railway mention in
`.env.example`, `vercel.json`) point at a single Railway web dyno today. This doc
replaces that with Tencent equivalents.

## Region

The hardware (modem-gateways) and stakeholders are Sri Lanka–based (Ideabiz is an
LK aggregator; phone numbers are normalized to `+94`). Tencent has no LK region, so
pick by measured latency from your actual gateway SIM/ISP paths — **ap-mumbai**
(Mumbai) is the geographically closest Tencent region to Sri Lanka; **ap-singapore**
has the fullest product parity (TDMQ, COS, CLB, TKE all mature there) and is the
common fallback. Default to Singapore unless you've measured Mumbai is meaningfully
better for the gateways' round-trip to the MQTT broker and `/api/events`.

---

## Phase 1 — MVP (matches current scale, fixes the worst prototype risks)

```
Internet
   │
   ▼
 DNSPod (DNS)
   │
   ▼
 CLB (TLS termination, Tencent SSL cert)
   │
   ▼
 CVM  (1 instance, Docker) ─────────────► TencentDB for PostgreSQL
   │  ├─ FastAPI (server.py)                 (replaces backend/data/*.json)
   │  └─ background MQTT client thread
   │        (outbound to broker.hivemq.com,   COS bucket (private)
   │         or a private broker — see below) (replaces backend/uploads/)
   │
   └─ serves dist/ directly (Phase 1; Phase 2 moves this to COS+CDN)

 Tencent CFW/WAF in front of CLB — /api/events and /upload are hit directly
 by field hardware and the public upload page, so they need rate limiting.
```

| Concern | Tencent service | Why now, not later |
|---|---|---|
| Compute | 1× **CVM** (or **Lighthouse** if you want Railway-like simplicity) running the existing Docker image | No code change to go from "one process" to "one process on Tencent" |
| Database | **TencentDB for PostgreSQL** | The app already speaks `DATABASE_URL` (`db.py`) — pointing it at managed Postgres and finishing the B1 cutover (`data_store.py` → `repo.py`) removes JSON's full-rewrite-per-write and no-locking risk before it corrupts data under real concurrent devices |
| Uploaded images | **COS** (private bucket) | Local disk on a single CVM is a single point of failure and doesn't survive an instance replace |
| Static SPA | Served by FastAPI initially, then **COS + CDN (Tencent EdgeOne or Tencent CDN)** | Cheap win, but not urgent at MVP scale — do it when you split compute in Phase 2 |
| TLS + entry point | **CLB** with a Tencent-managed SSL cert | Also gives you a stable IP/host to point DNS at independent of the CVM |
| WAF / rate limiting | **Tencent CFW (Cloud Firewall) / WAF** in front of the CLB | `/api/events` and `/upload` are public, unauthenticated-until-`X-API-Key` endpoints reachable from the internet |
| Secrets | Env vars via CVM/Docker secrets, or **Tencent SSM (Secrets Manager)** | See "Fix before going live" below — there's a hardcoded production SMS token in source today |
| DNS | **DNSPod** | Tencent-native, integrates with CLB/CDN health checks |

This tier is one CVM + one managed Postgres + one COS bucket + one CLB — it's
intentionally close to what's running on Railway today, so the migration is
"swap the host and finish the Postgres cutover," not a redesign.

---

## Phase 2 — Scale-out (Tencent mapping of `scaling.md` B1–B6)

Only build this once Phase 1's actually under load. It's the same stages already
decided in `scaling.md`, mapped onto managed services instead of self-run ones.

```
Internet
   │
   ▼
 CLB (TLS, session-aware for SSE)
   │
   ├──► TKE pods: API (FastAPI) ──────► TencentDB for PostgreSQL (+ read replica)
   │        (N replicas, autoscaled)          (time-partitioned detection_events,
   │                                            per B2 retention)
   ├──► TKE pods: worker (rules/spatial/
   │        notify, consumes the queue)
   │
   └──► TDMQ (Redis edition) or TencentDB for Redis
            - Streams: intake queue (B4)
            - Pub/Sub: SSE fan-out across API pods (B5)
            - Outbox: notification delivery state (B5)

 COS + CDN — SPA static assets, uploaded evidence photos
 TCR — container images, built by CI
 Cloud Monitor + CLS — metrics/logs feeding a real health check (B6)
 SSM — device api_keys, IDEABIZ_TOKEN, MQTT creds, DB creds
```

| `scaling.md` stage | What it needs | Tencent service |
|---|---|---|
| B1 — Postgres + async repo | Managed Postgres, connection pooling | **TencentDB for PostgreSQL** |
| B2 — Bounded queries + retention | Time-partitioned tables, archive job | Same DB; a scheduled **SCF (serverless function)** or a CronJob on TKE for the archive/drop job |
| B3 — Pagination + SSE push | No new infra; CLB must support long-lived SSE connections | **CLB** (already does) |
| B4 — Intake fast-path + async worker | A queue + a separately-scaled worker pool | **TDMQ** (Redis or RocketMQ engine) for the queue; a second **TKE** deployment (or CVM Auto Scaling group) for workers, scaled independently from the API |
| B5 — SSE fan-out + notification outbox | Pub/sub reachable from every API replica | Same **TDMQ/Redis** instance (separate logical DB/topic from the queue) |
| B6 — Ops hardening | Pooling, real health checks, metrics, rate limiting, secrets | **Cloud Monitor** (metrics/alerts), **CLS** (centralized logs), **SSM** (secrets), **WAF** (rate limiting on intake) |

Compute platform for this tier: **TKE** (not TKE Serverless) once you have an
API deployment and a worker deployment that need independent scaling and rolling
deploys — don't adopt Kubernetes before B4 exists, it buys you nothing over the
Phase-1 CVM until there are two things to scale independently.

---

## MQTT ingress — the one piece without a stock Tencent equivalent

Today the backend makes an **outbound** connection to the public
`broker.hivemq.com` and trusts an `api_key` embedded in the message payload for
auth — anyone who can reach that public broker can publish to those topics. Three
options, in order of effort:

1. **Keep the public HiveMQ broker** (zero change) — fine while gateways are few
   and trusted, matches what hardware already does.
2. **Self-host a private broker** (EMQX or Mosquitto) on a small CVM inside the
   VPC, with TLS + per-device username/password or client certs. Minimal code
   change (`MQTT_BROKER_HOST`/`MQTT_USE_TLS` are already env-driven per
   `.env.example`).
3. **TDMQ for MQTT** (Tencent's managed MQTT service, used for IoT device
   ingestion) — fully managed, per-device auth and ACLs, but is the option most
   likely to need code/topic changes on the gateway side. Worth it once the
   number of field gateways justifies not operating your own broker.

Start with option 2 when you outgrow the public broker; only reach for option 3
if you also want Tencent to own device provisioning/fleet management.

## CI/CD

`.github/workflows/build.yml` already builds the SPA on every push. Extend it (or
mirror it in Tencent CODING) to also build the backend Docker image, push to
**TCR (Tencent Container Registry)**, and roll it out — to the Phase-1 CVM via a
simple `docker pull && restart`, or to Phase-2 TKE via a rolling deployment.

## Fix before going live, regardless of host

`backend/notifier.py:136-139` falls back to a **hardcoded production Ideabiz URL,
sender port, and API token** when the env vars aren't set. That's a live SMS
credential committed to source. Move it to required env vars (fail loudly if
unset) backed by **Tencent SSM**, and rotate the token since it's already been
committed to git history.
