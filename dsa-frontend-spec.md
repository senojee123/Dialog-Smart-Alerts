# Dialog Smart Alerts — Frontend / Dashboard UI Spec

**Companion to:** SPEC.md, Integration Guide, Deployment Plan
**Stack:** React + Vite + Tailwind + Leaflet + lucide-react (SPEC §19)
**Theme:** white base, Dialog red primary, orange + maroon accents
**Last updated:** 2026-06-18

---

## 1. Purpose

The operations dashboard for 24/7 monitoring of detection incidents: see what's happening live, drill
into an incident, act (manual hardware override, close), and watch delivery/escalation in real time.
Desktop-first (a control desk), tablet-tolerant. Consumes the REST + SSE contracts in Integration
Guide §E.

---

## 2. Design system

### 2.1 Color tokens
Brand red is reserved for **chrome and primary actions**. Severity uses a **separate, hue-spread
scale** so criticality is legible at a glance and never collides with brand chrome. Confirm the exact
brand red against Dialog's official brand guide; values below are working defaults.

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#FFFFFF` | page background |
| `--surface` | `#F7F8FA` | cards, panels |
| `--surface-2` | `#F2F4F7` | nested panels, table headers |
| `--border` | `#E4E7EC` | dividers, card borders |
| `--text` | `#1A1A1A` | primary text |
| `--text-muted` | `#667085` | secondary text |
| `--brand` | `#DA1F26` | Dialog red — primary buttons, active nav, logo |
| `--brand-hover` | `#B81A20` | hover/pressed |
| `--accent-orange` | `#F2841C` | highlights, charts, HIGH severity |
| `--accent-maroon` | `#7B1E28` | top bar, headings band, emphasis |

**Severity scale** (always pair color with a label + icon — never color alone):

| Severity | Fill | Text on fill | Icon (lucide) |
|---|---|---|---|
| CRITICAL | `#D92D20` (+ subtle pulse) | white | `siren` |
| HIGH | `#F2841C` | white | `alert-triangle` |
| MEDIUM | `#F5B70A` | `#1A1A1A` | `alert-circle` |
| LOW | `#12B76A` | white | `info` |

**State colors:** delivery → `dispatched #667085`, `delivered #12B76A`, `failed #D92D20`. Hardware →
`ON #12B76A`, `OFF #98A2B3`, `OFFLINE #D92D20`, `ERROR #D92D20`, `MANUAL_OVERRIDE #7B1E28`.
Mode badge → `LIVE #D92D20`, `SHADOW #667085`.

### 2.2 Type, spacing, elevation
- Font: Inter (or system UI stack). Sizes: 12 / 14 (base) / 16 / 20 / 24 / 30.
- Spacing scale: 4-based (Tailwind default). Radius: `8px` cards, `6px` chips, `4px` inputs.
- Elevation: flat by default; a soft shadow (`shadow-sm`) only on the detail drawer and modals.
- Iconography: lucide-react throughout.

---

## 3. App shell

- **Top bar** (maroon band): logo + "Dialog Smart Alerts", global **operating-mode badge** (LIVE/SHADOW,
  SPEC §17), a **system-health dot** (green/amber/red → opens the health panel, §4.6), environment
  label (dev/staging/prod), user menu.
- **Left nav:** Live Incidents · Map · Devices · Hardware Units · Stakeholders · Rules · Admin.
  Active item uses brand red.
- **Main content:** routed per page.

---

## 4. Screens

### 4.1 Live Incidents (default route)
Three-region layout: **incident table (left ~55%) · map (right ~45%) · detail drawer (slides over,
on row click)**.

**Table columns** (one row per incident, newest/most-severe first):

| Column | Source field |
|---|---|
| Severity chip | `severity` |
| Incident | `incident_id` |
| Time | `opened_at` (relative, e.g. "2m ago") |
| Area / location | resolved zone + `location` |
| Object | `object` (+ `herd_size` if >1) |
| AI | `ai_confirmed` → ✓ / ✗ / "pending" / "timeout" |
| Notify | delivered/total counts, colored by worst channel state |
| Hardware | unit state badge |
| State | lifecycle `status` (SPEC §5) |

- **Filters:** severity, status, zone, time range, AI outcome. **Sort:** severity (default), time.
- **Live behavior:** new incidents slide in at top with a brief highlight; in-place updates flash the
  changed cell. CRITICAL rows are pinned above the sort and get the pulse + optional audible cue (§5).
- Clicking a row opens the detail drawer and focuses the map marker.

### 4.2 Incident Detail (drawer)
- **Header:** severity chip, `incident_id`, current `status`, area, opened-at; **Close incident** button.
- **Evidence:** image/video (`incident_media`); placeholder if media still attaching.
- **AI panel:** `ai_summary`, `confidence`, `risk_factors`, outcome (confirmed/rejected/timeout). If
  `OPERATOR_REVIEW` (VLM rejected, SPEC §4.3), show a clear banner: "AI could not confirm — warning
  active as precaution. Operator review required."
- **Derived facts:** `distance_to_road_m`, `is_night`, geofences hit, `detections_in_zone` — these
  explain *why* the rule fired (SPEC §8.2).
- **Rule(s) triggered:** name + severity.
- **Stakeholders table:** name/role, channel(s), per-channel **dispatched/delivered/failed**, **ack**
  (RECEIVED / RESPONDING / none, SPEC §10.4).
- **Hardware:** unit, state, `expires_at` countdown, **manual ON/OFF override** (confirms before
  acting; SPEC §11). Override is audited.
- **Timeline:** state transitions + audit entries, newest last.
- **Operator notes:** editable.

### 4.3 Map (full route)
Leaflet. Layers (toggleable): incidents (severity-colored markers; CRITICAL pulses), device locations,
hardware units (state-colored), geofence overlays (road/rail/village/etc.). Marker click → mini-card
with a "open detail" link. Filter by severity/zone. Auto-pan to new CRITICAL incidents (with a
"following live" toggle so it doesn't yank the operator around).

### 4.4 Admin (CRUD tables)
Stakeholders · Devices · Hardware Units · Geofences · Rules · Escalation Policies · Notification
Templates. Standard list + create/edit forms. Rules editor exposes the JSON condition builder
(SPEC §8.3) — start with a raw-JSON editor + validation, upgrade to a visual builder later.

### 4.5 Devices / Hardware Units
Health lists: last heartbeat, online/offline (dead-man's-switch, SPEC §16), reliability; for units,
current state + manual control + recent `hardware_actions`.

### 4.6 System health panel (SPEC §16)
Opened from the top-bar health dot: queue depth, worker liveness, VLM/provider health, broker
connectivity, outbox backlog, fast-path latency vs the ≤1.5s SLO. Red dot when any is degraded so the
operator interprets alerts correctly.

---

## 5. Realtime & critical-incident UX

- **SSE wiring** (Integration Guide §E.2): on mount, `GET /incidents` snapshot → render → attach
  `EventSource` to `/stream/incidents`. Apply events by `incident_id` (idempotent, keyed on
  `updated_at`). On reconnect the browser resends `Last-Event-ID`; trust the server replay. Show a
  small "live / reconnecting" indicator tied to `EventSource.readyState`.
- **CRITICAL cue:** new CRITICAL incident → pin + pulse + an **optional, operator-toggleable audible
  alert** (Web Audio). Mute control in the top bar; default on for an unattended desk.
- Never build initial state from the stream alone — snapshot first, stream for deltas.

---

## 6. States & feedback
- **Loading:** skeleton rows/cards, not spinners, for the table and detail.
- **Empty:** "No active incidents" with a calm illustration (not alarming).
- **Error:** inline retry on a failed fetch; a persistent banner if the SSE stream is down ("Live
  updates paused — reconnecting").
- **Optimistic actions:** manual hardware override and close update the UI immediately, reconcile on
  server confirmation, and roll back with a toast on failure.

---

## 7. Accessibility & contrast
- White + red: use red as a **fill with white text**, not small red text on white (contrast). Verify
  AA contrast on all chips.
- **Never rely on color alone** — every severity/state has a label and icon (color-blind safety).
- Full keyboard nav: table rows focusable, drawer trap-focus + Esc to close, all actions reachable.

---

## 8. Responsive
- ≥1280px: three-region live view as described.
- 768–1279px: map collapses to a toggle; table full width; detail becomes a full-screen drawer.
- <768px: read-only triage (list + detail); admin is desktop-only.

---

## 9. Suggested structure (Vite + React)

```
src/
  main.jsx
  App.jsx                  # router + shell
  theme/
    tokens.css             # CSS variables from §2.1
    tailwind.config.js     # maps tokens → Tailwind colors
  api/
    client.js              # fetch wrapper, auth header, error envelope
    stream.js              # EventSource helper (reconnect, Last-Event-ID)
  hooks/
    useAuth.js
    useIncidents.js        # snapshot + cache
    useIncidentStream.js   # SSE → merges into cache (idempotent)
    useSystemHealth.js
  lib/
    severity.js            # severity → color/icon/label maps
    format.js              # relative time, distance, counts
  components/
    shell/ TopBar.jsx NavSidebar.jsx ModeBadge.jsx HealthDot.jsx
    incidents/ IncidentTable.jsx IncidentRow.jsx IncidentDetail.jsx
               StakeholderStatus.jsx Timeline.jsx HardwareControl.jsx
    common/ SeverityChip.jsx StatusBadge.jsx Skeleton.jsx Toast.jsx ConfirmDialog.jsx
    map/ MapPanel.jsx Markers.jsx GeofenceLayers.jsx
  pages/
    LiveIncidents.jsx MapView.jsx Devices.jsx HardwareUnits.jsx
    admin/ Stakeholders.jsx Rules.jsx EscalationPolicies.jsx Templates.jsx
```

### Tailwind color extension (`tailwind.config.js`)
```js
theme: { extend: { colors: {
  brand:   { DEFAULT: '#DA1F26', hover: '#B81A20' },
  maroon:  '#7B1E28',
  orange:  '#F2841C',
  sev: { critical: '#D92D20', high: '#F2841C', medium: '#F5B70A', low: '#12B76A' },
  surface: { DEFAULT: '#F7F8FA', alt: '#F2F4F7' },
  ink:     { DEFAULT: '#1A1A1A', muted: '#667085' },
  line:    '#E4E7EC',
}}}
```

---

## 10. Build order (frontend)
1. Shell + theme tokens + nav + mode/health indicators.
2. Live Incidents table against `GET /incidents` (mock data first — the simulator, SPEC §12).
3. Incident detail drawer (read-only).
4. SSE live updates (snapshot → stream, §5).
5. Actions: manual hardware override + close (optimistic).
6. Map panel + layers.
7. Admin CRUD.
8. System-health panel + audible critical cue.

Start at step 2 against the simulator and you'll have a clickable live board before any real device
exists.

---

## Changelog
- **2026-06-18:** Initial frontend spec. Theme: white + Dialog red + orange/maroon. Severity scale
  hue-spread and separated from brand chrome. SSE robustness + critical-cue UX defined.
