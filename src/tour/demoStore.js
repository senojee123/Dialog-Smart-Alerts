/**
 * Tour data layer.
 *
 * While the guided tour runs, the data hooks (`useApi`, `useIncidents`) read
 * from this in-memory store instead of the backend, so the tour can play a
 * scripted, live-looking scenario (detections → incidents → notifications →
 * LED boards) without writing anything to the real data store. Stopping the
 * tour hands every page back to live data.
 *
 * It mirrors the backend's behaviour closely: the rule engine (single
 * detection → HIGH, two in the same zone → CRITICAL) and the spatial engine
 * (boards within the propagation radius go RED → AMBER → GREEN), with the
 * decay timings shortened so the tour can show a full cycle in seconds.
 */

import { useSyncExternalStore } from 'react'
import { haversineM } from '../lib/geo.js'
import evidenceImg from '../assets/tour-evidence.jpg'

const LNG = 81.48
const RADIUS_M = 90
const RED_HOLD_MS = 5000
const AMBER_HOLD_MS = 13000

// ── external store plumbing ──────────────────────────────────────────────────

let state = { active: false, version: 0, data: {} }
const listeners = new Set()
const timers = new Set()
let spatialTimer = null
let incSeq = 0

function commit(patch) {
  state = { ...state, ...patch, version: state.version + 1 }
  listeners.forEach(l => l())
}

function setCollection(key, rows) {
  commit({ data: { ...state.data, [key]: rows } })
}

function later(ms, fn) {
  const t = setTimeout(() => { timers.delete(t); if (state.active) fn() }, ms)
  timers.add(t)
}

export function subscribe(l) { listeners.add(l); return () => listeners.delete(l) }
export function getSnapshot() { return state }

export function useDemoState() {
  return useSyncExternalStore(subscribe, getSnapshot)
}

/** Demo rows for a REST endpoint (e.g. '/api/devices'), or null when not demoing. */
export function useDemoCollection(endpoint) {
  const s = useDemoState()
  if (!s.active) return null
  const key = endpointKey(endpoint)
  return key && s.data[key] ? s.data[key] : null
}

function endpointKey(endpoint) {
  const m = /^\/api\/([a-z-]+)\/?$/.exec(endpoint || '')
  return m ? m[1] : null
}

// ── helpers ──────────────────────────────────────────────────────────────────

const iso = (msAgo = 0) => new Date(Date.now() - msAgo).toISOString()
const MIN = 60 * 1000

function nextIncidentId() {
  const d = new Date()
  const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
  incSeq += 1
  return `INC-${ymd}-${String(incSeq).padStart(4, '0')}`
}

function stakeholderEntry(sh, status = 'dispatched') {
  return {
    id: sh.id, name: sh.name, role: sh.role,
    channels: sh.channels.map(c => ({ type: c.type, status, ack: null })),
  }
}

// ── seed fixtures ────────────────────────────────────────────────────────────

const ZONES = [
  { id: 'ZONE-B43', name: 'B43 Yala Road Corridor', use_case_id: 'UC-001', road: 'B43', lat: 6.3818, lng: LNG },
  { id: 'ZONE-A2',  name: 'A2 Southern Highway',     use_case_id: 'UC-001', road: 'A2',  lat: 6.2812, lng: 81.3902 },
  { id: 'ZONE-KTR', name: 'Kataragama Road',         use_case_id: 'UC-001', road: 'KTR', lat: 6.3720, lng: 81.3310 },
]

// No contact details: channel types only (nothing here is ever sent).
const STAKEHOLDERS = [
  { id: 'SH-001', name: 'Park Warden – Yala', role: 'Wildlife Officer', org: 'Department of Wildlife Conservation',
    use_case_ids: ['UC-001'], on_call: true,
    channels: [{ type: 'sms', language: 'en' }, { type: 'whatsapp', language: 'en' }] },
  { id: 'SH-002', name: 'Traffic Control – Southern Province', role: 'Traffic Controller', org: 'Road Development Authority',
    use_case_ids: ['UC-001'], on_call: true,
    channels: [{ type: 'sms', language: 'en' }, { type: 'email', language: 'en' }] },
  { id: 'SH-003', name: 'Police – Tissamaharama', role: 'Law Enforcement', org: 'Sri Lanka Police',
    use_case_ids: ['UC-001'], on_call: false,
    channels: [{ type: 'sms', language: 'en' }] },
  { id: 'SH-004', name: 'DWC Operations Centre', role: 'Operations', org: 'Department of Wildlife Conservation',
    use_case_ids: ['UC-001'], on_call: true,
    channels: [{ type: 'sms', language: 'en' }, { type: 'whatsapp', language: 'en' }] },
]
const SH = Object.fromEntries(STAKEHOLDERS.map(s => [s.id, s]))

const RULES = [
  {
    id: 'RULE-001', use_case_id: 'UC-001', name: 'Single Detection – High Alert',
    description: 'Any device detects an elephant with ≥60% confidence.', priority: 1, active: true,
    conditions: [{ field: 'object_type', op: 'eq', value: 'elephant' }, { field: 'confidence', op: 'gte', value: 60 }],
    confirmation: null,
    actions: { on_trigger: {
      create_incident: true, incident_severity: 'HIGH', notify_stakeholder_ids: ['SH-001', 'SH-004'],
      actuate_sign_ids: [], sign_state: 'CAUTION',
      message_template: '[HIGH] Possible elephant near {zone_name} ({device_name}). Confidence {confidence}%. Please verify. Incident {incident_id}',
    } },
  },
  {
    id: 'RULE-002', use_case_id: 'UC-001', name: 'Dual Confirmation – Critical Alert',
    description: 'Two or more detections in the same zone within 15 minutes.', priority: 2, active: true,
    conditions: [{ field: 'object_type', op: 'eq', value: 'elephant' }, { field: 'confidence', op: 'gte', value: 70 }],
    confirmation: { required_count: 2, window_seconds: 900, same_zone: true },
    actions: {
      on_trigger: {
        create_incident: true, incident_severity: 'HIGH', notify_stakeholder_ids: ['SH-001'],
        actuate_sign_ids: [], sign_state: 'CAUTION',
        message_template: '[HIGH] Elephant near {zone_name}. Awaiting confirmation. Incident {incident_id}',
      },
      on_confirm: {
        create_incident: true, incident_severity: 'CRITICAL', notify_stakeholder_ids: ['SH-001', 'SH-002', 'SH-003', 'SH-004'],
        actuate_sign_ids: [], sign_state: 'WARNING',
        message_template: '[CRITICAL] CONFIRMED elephant on {zone_name}. Multiple detections. All units respond. Incident {incident_id}',
      },
    },
  },
]

const USE_CASES = [{
  id: 'UC-001', name: 'Elephant Detection – Road Corridor',
  description: 'Detect elephants near road corridors and alert stakeholders. Nearby LED boards light automatically by proximity to the detection.',
  active: true, icon: 'elephant', color: '#D92D20',
  spatial: { mode: 'radius', propagation_radius_m: RADIUS_M, red_hold_s: 90, amber_hold_s: 420, min_confidence: 55 },
}]

function buildDevices() {
  const cams = [6.3796, 6.3809, 6.3822, 6.3835].map((lat, i) => ({
    id: `CAM-B43-0${i + 1}`, name: `B43 Camera ${i + 1}`, type: i === 2 ? 'thermal' : 'camera',
    use_case_id: 'UC-001', zone_id: 'ZONE-B43', lat, lng: LNG + (i % 2 ? 0.0004 : -0.0004),
    online: true, last_seen: iso(5000 + i * 3000), external_id: `A4:CF:12:0${i}:7E:1${i}`,
  }))
  return [
    ...cams,
    { id: 'CAM-A2-01', name: 'A2 Camera 1', type: 'camera', use_case_id: 'UC-001', zone_id: 'ZONE-A2',
      lat: 6.2812, lng: 81.3902, online: true, last_seen: iso(9000), external_id: 'A4:CF:12:10:7E:20' },
    { id: 'ACU-KTR-01', name: 'Kataragama Acoustic Array', type: 'acoustic', use_case_id: 'UC-001', zone_id: 'ZONE-KTR',
      lat: 6.3720, lng: 81.3310, online: true, last_seen: iso(12000), external_id: 'A4:CF:12:20:7E:30' },
  ]
}

function buildSigns() {
  return [6.3794, 6.3801, 6.3808, 6.3815, 6.3822, 6.3829, 6.3836, 6.3843].map((lat, i) => ({
    id: `SIGN-B43-${String(i + 1).padStart(2, '0')}`, name: `B43 Board ${i + 1}`,
    use_case_id: 'UC-001', zone_id: 'ZONE-B43', road: 'B43 Yala Road', km_marker: (12 + i * 0.08).toFixed(2),
    lat, lng: LNG, online: true, state: 'CLEAR', updated_at: iso(40 * MIN),
  }))
}

/** Earlier-today history so charts and counters have a believable shape. */
function buildHistory(devices) {
  const now = new Date()
  const startOfDay = new Date(now); startOfDay.setHours(0, 0, 0, 0)
  const elapsed = now - startOfDay
  const events = []
  // Evening/early-morning heavy distribution, only for hours already passed today.
  const hourWeights = [3, 2, 2, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 2, 2, 3, 4, 3, 3, 2, 2]
  let n = 0
  hourWeights.forEach((w, h) => {
    for (let k = 0; k < w; k++) {
      const t = startOfDay.getTime() + h * 3600000 + ((k * 17 + h * 7) % 55) * 60000
      if (t - startOfDay.getTime() > elapsed - 20 * MIN) continue
      const dev = devices[(h + k) % devices.length]
      n++
      events.push({
        id: `EVT-H${n}`, device_id: dev.id, use_case_id: 'UC-001', object_type: 'elephant',
        confidence: 72 + ((h * 13 + k * 7) % 25), lat: dev.lat, lng: dev.lng, zone_id: dev.zone_id,
        received_at: new Date(t).toISOString(), source: 'device',
        false_positive: n % 9 === 0, pending_confirmation: false,
      })
    }
  })
  return events.sort((a, b) => new Date(b.received_at) - new Date(a.received_at))
}

function historicIncidents() {
  const mk = (minsAgo, zone, zoneName, desc, lat, lng, dev, sev, status, conf, extra = {}) => {
    const id = nextIncidentId()
    const opened = iso(minsAgo * MIN)
    return {
      id, incident_id: id, severity: sev, status, opened_at: opened, updated_at: iso((minsAgo - 18) * MIN),
      object: 'elephant', herd_size: 1, number_of_elephants: extra.herd ?? 1,
      location: { lat, lng, description: desc }, zone: zoneName, zone_id: zone, zone_name: zoneName, device_id: dev,
      ai_confirmed: conf >= 0.6, confidence: conf, incident_media: evidenceImg,
      ai_summary: extra.summary ?? `Elephant detected by ${dev} at ${Math.round(conf * 100)}% confidence.`,
      risk_factors: extra.risk ?? ['road_proximity'], detections_in_zone: extra.count ?? 1,
      rules_triggered: [{ name: 'Single Detection – High Alert', severity: 'HIGH' }],
      stakeholders: [SH['SH-001'], SH['SH-004']].map(s => ({ ...stakeholderEntry(s, 'delivered'),
        channels: s.channels.map((c, i) => ({ type: c.type, status: 'delivered', ack: i === 0 ? 'RECEIVED' : null })) })),
      hardware: { unit_id: 'HW-B43-SIREN', name: 'B43 Roadside Siren', state: 'OFF', expires_at: null },
      timeline: [
        { ts: opened, event: `Detection received from ${dev}` },
        { ts: opened, event: 'Rule matched — Single Detection – High Alert' },
        { ts: iso((minsAgo - 1) * MIN), event: 'Stakeholders notified (2 contacts, 4 channels)' },
        { ts: iso((minsAgo - 18) * MIN), event: status === 'OPERATOR_REVIEW' ? 'Flagged for operator review' : 'No detections for 15 minutes — incident auto-resolved' },
      ],
      operator_notes: '', ...extra.more,
    }
  }
  return [
    mk(52, 'ZONE-A2', 'A2 Southern Highway', 'Near km 214 culvert', 6.2812, 81.3902, 'CAM-A2-01', 'MEDIUM', 'OPERATOR_REVIEW', 0.58,
      { summary: 'Possible elephant partially occluded by vegetation near the culvert. Precautionary alert raised for operator review.', risk: ['night_movement'] }),
    mk(140, 'ZONE-B43', 'B43 Yala Road Corridor', 'B43 km 12.3, east verge', 6.3812, LNG, 'CAM-B43-02', 'HIGH', 'RESOLVED', 0.87,
      { herd: 2, count: 3, summary: 'Two elephants grazing along the east verge; moved back into the forest line.' }),
    mk(310, 'ZONE-KTR', 'Kataragama Road', 'Kataragama Rd, Sella junction', 6.3720, 81.3310, 'ACU-KTR-01', 'HIGH', 'CLOSED', 0.81,
      { summary: 'Low-frequency rumble signature matched elephant vocalisation near the junction.' }),
  ]
}

// ── spatial engine (shortened decay for the tour) ────────────────────────────

let hits = [] // { lat, lng, t }

function recomputeSigns() {
  const signs = state.data['road-signs']
  if (!signs) return
  const now = Date.now()
  let changed = false
  const next = signs.map(sign => {
    let newest = null
    for (const h of hits) {
      if (haversineM(sign.lat, sign.lng, h.lat, h.lng) <= RADIUS_M && (!newest || h.t > newest)) newest = h.t
    }
    const age = newest == null ? Infinity : now - newest
    const s = age < RED_HOLD_MS ? 'WARNING' : age < AMBER_HOLD_MS ? 'CAUTION' : 'CLEAR'
    if (s === sign.state) return sign
    changed = true
    return { ...sign, state: s, updated_at: new Date().toISOString() }
  })
  if (changed) setCollection('road-signs', next)
}

// ── public API ───────────────────────────────────────────────────────────────

export function startDemo() {
  stopDemo()
  incSeq = 0
  hits = []
  const devices = buildDevices()
  commit({
    active: true,
    data: {
      'use-cases': USE_CASES,
      zones: ZONES,
      stakeholders: STAKEHOLDERS,
      rules: RULES,
      devices,
      'road-signs': buildSigns(),
      events: buildHistory(devices),
      incidents: historicIncidents(),
      notifications: [],
    },
  })
  spatialTimer = setInterval(() => {
    recomputeSigns()
    // Keep device heartbeats fresh.
    const devs = state.data.devices
    if (devs && Math.random() < 0.25) {
      const i = Math.floor(Math.random() * devs.length)
      setCollection('devices', devs.map((d, k) => k === i ? { ...d, last_seen: iso() } : d))
    }
  }, 500)
}

export function stopDemo() {
  timers.forEach(clearTimeout)
  timers.clear()
  if (spatialTimer) clearInterval(spatialTimer)
  spatialTimer = null
  hits = []
  if (state.active) commit({ active: false, data: {} })
}

export function isDemoActive() { return state.active }

function patchIncident(id, fn) {
  const list = state.data.incidents || []
  setCollection('incidents', list.map(i => i.incident_id === id ? fn(i) : i))
}

function scheduleDelivery(id, stakeholderIds, baseDelay = 1200) {
  stakeholderIds.forEach((sid, k) => {
    later(baseDelay + k * 700, () => patchIncident(id, inc => ({
      ...inc,
      stakeholders: inc.stakeholders.map(s => s.id !== sid ? s
        : { ...s, channels: s.channels.map(c => ({ ...c, status: 'delivered' })) }),
      updated_at: iso(),
    })))
  })
  // The on-call warden acknowledges shortly after.
  later(baseDelay + stakeholderIds.length * 700 + 2500, () => patchIncident(id, inc => {
    if (!inc.stakeholders.some(s => s.id === 'SH-001' && !s.channels[0].ack)) return inc
    return {
      ...inc,
      stakeholders: inc.stakeholders.map(s => s.id !== 'SH-001' ? s
        : { ...s, channels: s.channels.map((c, i) => i === 0 ? { ...c, ack: 'RESPONDING' } : c) }),
      timeline: [...inc.timeline, { ts: iso(), event: 'Park Warden – Yala responded via SMS — en route' }],
      updated_at: iso(),
    }
  }))
}

/**
 * One detection from a device — runs the same decisions the backend makes:
 * open a HIGH incident, or confirm/escalate an open one in the same zone.
 */
export function detect({ deviceId, lat, lng, confidence = 91, herd = 1 }) {
  if (!state.active) return null
  const devices = state.data.devices
  const dev = devices.find(d => d.id === deviceId) || devices[0]
  lat = lat ?? dev.lat
  lng = lng ?? dev.lng
  const zone = ZONES.find(z => z.id === dev.zone_id)
  const now = iso()

  const event = {
    id: `EVT-${Date.now().toString(36).toUpperCase()}`, device_id: dev.id, use_case_id: 'UC-001',
    object_type: 'elephant', confidence, lat, lng, zone_id: dev.zone_id, received_at: now,
    source: 'device', false_positive: false, pending_confirmation: false,
  }
  setCollection('events', [event, ...state.data.events])
  setCollection('devices', devices.map(d => d.id === dev.id ? { ...d, last_seen: now } : d))
  hits = [...hits, { lat, lng, t: Date.now() }]
  recomputeSigns()

  const open = (state.data.incidents || []).find(i =>
    i.zone_id === dev.zone_id && (i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW'))

  if (!open) {
    const id = nextIncidentId()
    const ids = RULES[0].actions.on_trigger.notify_stakeholder_ids
    const inc = {
      id, incident_id: id, severity: 'HIGH', status: 'ACTIVE', opened_at: now, updated_at: now,
      object: 'elephant', herd_size: herd, number_of_elephants: herd,
      location: { lat, lng, description: `B43 km ${(12 + (lat - 6.3794) / 0.0007 * 0.08).toFixed(2)}, roadside` },
      zone: zone.name, zone_id: zone.id, zone_name: zone.name, device_id: dev.id,
      ai_confirmed: true, confidence: confidence / 100, incident_media: evidenceImg,
      ai_summary: `Adult elephant detected by ${dev.name} approaching the carriageway, ${Math.round(confidence)}% confidence.`,
      risk_factors: ['road_proximity', 'evening_traffic'], detections_in_zone: 1,
      rules_triggered: [{ name: 'Single Detection – High Alert', severity: 'HIGH' }],
      stakeholders: ids.map(sid => stakeholderEntry(SH[sid])),
      hardware: { unit_id: 'HW-B43-SIREN', name: 'B43 Roadside Siren', state: 'OFF', expires_at: null },
      timeline: [
        { ts: now, event: `Detection received from ${dev.id} — elephant, ${Math.round(confidence)}%` },
        { ts: now, event: 'Rule matched — Single Detection – High Alert' },
        { ts: now, event: `LED boards within ${RADIUS_M} m switched to WARNING` },
        { ts: now, event: `Stakeholders notified (${ids.length} contacts, ${ids.reduce((n, s) => n + SH[s].channels.length, 0)} channels)` },
      ],
      operator_notes: '',
    }
    setCollection('incidents', [inc, ...state.data.incidents])
    scheduleDelivery(id, ids)
    return id
  }

  const count = (open.detections_in_zone || 1) + 1
  const escalate = open.severity !== 'CRITICAL' && confidence >= 70
  const newIds = escalate
    ? RULES[1].actions.on_confirm.notify_stakeholder_ids.filter(sid => !open.stakeholders.some(s => s.id === sid))
    : []
  patchIncident(open.incident_id, inc => ({
    ...inc,
    severity: escalate ? 'CRITICAL' : inc.severity,
    detections_in_zone: count,
    confidence: Math.max(inc.confidence, confidence / 100),
    location: { ...inc.location, lat, lng },
    device_id: dev.id,
    herd_size: Math.max(inc.herd_size || 1, herd),
    number_of_elephants: Math.max(inc.number_of_elephants || 1, herd),
    ai_summary: escalate
      ? `Confirmed: ${herd > 1 ? `${herd} elephants` : 'elephant'} moving along the B43 corridor, seen by ${count} detections across adjacent cameras.`
      : inc.ai_summary,
    rules_triggered: escalate
      ? [...inc.rules_triggered, { name: 'Dual Confirmation – Critical Alert', severity: 'CRITICAL' }]
      : inc.rules_triggered,
    stakeholders: [...inc.stakeholders, ...newIds.map(sid => stakeholderEntry(SH[sid]))],
    hardware: escalate
      ? { ...inc.hardware, state: 'ON', expires_at: new Date(Date.now() + 30 * MIN).toISOString() }
      : inc.hardware,
    timeline: [
      ...inc.timeline,
      { ts: iso(), event: `Detection received from ${dev.id} — elephant, ${Math.round(confidence)}%` },
      ...(escalate ? [
        { ts: iso(), event: `Rule matched — Dual Confirmation (${count} detections in zone)` },
        { ts: iso(), event: 'Severity escalated HIGH → CRITICAL' },
        { ts: iso(), event: 'Roadside siren HW-B43-SIREN activated (auto, 30 min)' },
        { ts: iso(), event: `Escalation sent to ${newIds.length} more contacts` },
      ] : []),
    ],
    updated_at: iso(),
  }))
  if (newIds.length) scheduleDelivery(open.incident_id, newIds, 900)
  return open.incident_id
}

/** A target walking along a path: one detection per step, nearest camera reports it. */
export function moveTarget(path, { steps = 6, stepMs = 2500, confidence = 88, herd = 1 } = {}) {
  for (let i = 0; i < steps; i++) {
    later(i * stepMs, () => {
      const f = steps > 1 ? i / (steps - 1) : 0
      const seg = Math.min(path.length - 2, Math.floor(f * (path.length - 1)))
      const local = f * (path.length - 1) - seg
      const [a, b] = [path[seg], path[seg + 1] || path[seg]]
      const lat = a[0] + (b[0] - a[0]) * local
      const lng = a[1] + (b[1] - a[1]) * local
      const cams = state.data.devices.filter(d => d.zone_id === 'ZONE-B43')
      const dev = cams.reduce((best, d) =>
        haversineM(lat, lng, d.lat, d.lng) < haversineM(lat, lng, best.lat, best.lng) ? d : best)
      detect({ deviceId: dev.id, lat, lng, confidence: confidence + ((i * 5) % 9), herd })
    })
  }
}

export function resolveActive() {
  const list = state.data.incidents || []
  const now = iso()
  setCollection('incidents', list.map(i => i.status !== 'ACTIVE' ? i : {
    ...i, status: 'RESOLVED', updated_at: now,
    hardware: { ...i.hardware, state: 'OFF', expires_at: null },
    timeline: [...i.timeline,
      { ts: now, event: 'No detections for 15 minutes — incident auto-resolved' },
      { ts: now, event: 'LED boards returned to ROAD CLEAR' },
      { ts: now, event: 'All-clear sent to stakeholders' }],
  }))
  hits = []
  recomputeSigns()
}

/** Latest active incident id (for the tour to open its detail). */
export function latestActiveIncidentId() {
  const list = (state.data.incidents || []).filter(i => i.status === 'ACTIVE')
  list.sort((a, b) => (a.severity === 'CRITICAL' ? -1 : 0) - (b.severity === 'CRITICAL' ? -1 : 0))
  return list[0]?.incident_id ?? null
}

// Mutations made through the normal UI while demoing stay local to the demo.
export function demoUpdate(endpoint, id, patch) {
  const key = endpointKey(endpoint)
  if (!key || !state.data[key]) return null
  let updated = null
  setCollection(key, state.data[key].map(r => {
    if (r.id !== id && r.incident_id !== id) return r
    updated = { ...r, ...patch, updated_at: iso() }
    return updated
  }))
  return updated
}

export function demoRemove(endpoint, id) {
  const key = endpointKey(endpoint)
  if (!key || !state.data[key]) return
  setCollection(key, state.data[key].filter(r => r.id !== id && r.incident_id !== id))
}
