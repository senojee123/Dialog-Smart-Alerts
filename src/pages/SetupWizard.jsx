import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2, MapPin, Camera, Thermometer, Plane, Radio, Activity,
         Phone, Mail, MessageSquare, Crosshair, CheckCircle, Rocket } from 'lucide-react'
import {
  Field, Input, Select, Textarea, Btn, Badge, ErrorBanner,
} from '../components/admin/CrudShell.jsx'
import WizardMap from '../components/wizard/WizardMap.jsx'
import { WizardProgress, WizardFooter, StepHeading } from '../components/wizard/WizardShell.jsx'

const STEPS = ['Use Case', 'Inputs', 'Outputs', 'Spatial Logic', 'Notifications', 'Review']

const DEVICE_TYPES = ['camera', 'thermal', 'drone', 'acoustic', 'pressure_pad', 'manual']
const TYPE_ICON = { camera: Camera, thermal: Thermometer, drone: Plane, acoustic: Radio, pressure_pad: Activity, manual: Activity }
const CHANNEL_TYPES = [
  { value: 'sms', label: 'SMS', icon: Phone },
  { value: 'whatsapp', label: 'WhatsApp', icon: MessageSquare },
  { value: 'email', label: 'Email', icon: Mail },
]

const DEFAULT_SPATIAL = { mode: 'radius', propagation_radius_m: 120, red_hold_s: 90, amber_hold_s: 420, min_confidence: 55 }
const DEFAULT_CENTER = [6.3818, 81.48]

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.status === 204 ? null : res.json()
}

function haversineM(aLat, aLng, bLat, bLng) {
  const R = 6371000, toRad = d => (d * Math.PI) / 180
  const dPhi = toRad(bLat - aLat), dLmb = toRad(bLng - aLng)
  const x = Math.sin(dPhi / 2) ** 2 + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLmb / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x))
}

export default function SetupWizard() {
  const navigate = useNavigate()
  const [step, setStep]             = useState(0)
  const [maxReached, setMaxReached] = useState(0)
  const [busy, setBusy]             = useState(false)
  const [error, setError]           = useState(null)

  // identifiers created in step 1
  const [ucId, setUcId]     = useState(null)
  const [zoneId, setZoneId] = useState(null)

  // step 1 form + spatial
  const [uc, setUc]           = useState({ name: '', description: '', color: '#D92D20' })
  const [spatial, setSpatial] = useState(DEFAULT_SPATIAL)

  // live collections for this use case
  const [devices, setDevices]           = useState([])
  const [signs, setSigns]               = useState([])
  const [stakeholders, setStakeholders] = useState([])
  const [rules, setRules]               = useState([])

  const reload = useCallback(async (id = ucId, zid = zoneId) => {
    if (!id) return
    const [devs, sgs, shs, rls] = await Promise.all([
      api('GET', '/api/devices'), api('GET', '/api/road-signs'),
      api('GET', '/api/stakeholders'), api('GET', '/api/rules'),
    ])
    setDevices(devs.filter(d => d.use_case_id === id))
    setSigns(sgs.filter(s => s.zone_id === zid))
    setStakeholders(shs.filter(s => (s.use_case_ids || []).includes(id)))
    setRules(rls.filter(r => r.use_case_id === id))
  }, [ucId, zoneId])

  const center = devices[0] ? [devices[0].lat, devices[0].lng]
    : signs[0] ? [signs[0].lat, signs[0].lng] : DEFAULT_CENTER

  function goTo(i) { setStep(i); setMaxReached(m => Math.max(m, i)) }

  async function guard(fn) {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  // ── step 1 commit ───────────────────────────────────────────────────────────
  async function commitUseCase() {
    await guard(async () => {
      if (!uc.name.trim()) throw new Error('Use case name is required')
      if (ucId) {
        await api('PUT', `/api/use-cases/${ucId}`, { name: uc.name, description: uc.description, color: uc.color })
      } else {
        const created = await api('POST', '/api/use-cases', { ...uc, active: false, spatial })
        const zone = await api('POST', '/api/zones', {
          name: `${uc.name} Zone`, use_case_id: created.id, lat: DEFAULT_CENTER[0], lng: DEFAULT_CENTER[1],
        })
        setUcId(created.id); setZoneId(zone.id)
        await reload(created.id, zone.id)
      }
      goTo(1)
    })
  }

  async function commitSpatial() {
    await guard(async () => {
      await api('PUT', `/api/use-cases/${ucId}`, { spatial })
      goTo(4)
    })
  }

  async function activate() {
    await guard(async () => {
      await api('PUT', `/api/use-cases/${ucId}`, { active: true, spatial })
      navigate('/road-signs')
    })
  }

  // ── render ────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-6 pt-5 pb-1 shrink-0">
        <h1 className="text-xl font-semibold text-ink flex items-center gap-2">
          <Rocket size={18} className="text-brand" /> Setup Wizard
        </h1>
        <p className="text-sm text-ink-muted mt-0.5">Configure a detection use case end-to-end. Each step saves as you go.</p>
      </div>

      <WizardProgress steps={STEPS} current={step} maxReached={maxReached} onStepClick={goTo} />

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto">
          <ErrorBanner error={error} />

          {step === 0 && <StepUseCase uc={uc} setUc={setUc} />}
          {step === 1 && <StepDevices {...{ ucId, zoneId, devices, center, reload, guard }} />}
          {step === 2 && <StepSigns {...{ zoneId, devices, signs, center, reload, guard }} />}
          {step === 3 && <StepSpatial {...{ spatial, setSpatial, devices, signs, center }} />}
          {step === 4 && <StepNotify {...{ ucId, stakeholders, rules, signs, reload, guard }} />}
          {step === 5 && <StepReview {...{ uc, spatial, devices, signs, stakeholders, rules }} />}
        </div>
      </div>

      {/* Footer nav */}
      {step === 0 && (
        <WizardFooter canBack={false} onNext={commitUseCase} busy={busy}
          nextDisabled={!uc.name.trim()} hint="Creates the use case and its zone" />
      )}
      {step === 1 && (
        <WizardFooter onBack={() => goTo(0)} onNext={() => goTo(2)} busy={busy}
          nextDisabled={devices.length === 0}
          hint={devices.length === 0 ? 'Add at least one input device' : `${devices.length} device(s) added`} />
      )}
      {step === 2 && (
        <WizardFooter onBack={() => goTo(1)} onNext={() => goTo(3)} busy={busy}
          nextDisabled={signs.length === 0}
          hint={signs.length === 0 ? 'Add at least one LED board' : `${signs.length} board(s) added`} />
      )}
      {step === 3 && (
        <WizardFooter onBack={() => goTo(2)} onNext={commitSpatial} busy={busy}
          hint="Saves the proximity + timing config" />
      )}
      {step === 4 && (
        <WizardFooter onBack={() => goTo(3)} onNext={() => goTo(5)} busy={busy}
          nextDisabled={stakeholders.length === 0 || rules.length === 0}
          hint={stakeholders.length === 0 ? 'Add at least one stakeholder'
            : rules.length === 0 ? 'Create at least one rule' : 'Ready to review'} />
      )}
      {step === 5 && (
        <WizardFooter onBack={() => goTo(4)} onNext={activate} busy={busy}
          nextLabel="Activate & Finish" hint="Activates the use case and opens the dashboard" />
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 1 — Use Case
// ════════════════════════════════════════════════════════════════════════════

function StepUseCase({ uc, setUc }) {
  const set = (k, v) => setUc(s => ({ ...s, [k]: v }))
  return (
    <div>
      <StepHeading title="Name your use case"
        description="A use case is the container for one detection scenario — its devices, signs, rules and stakeholders." />
      <div className="space-y-4">
        <Field label="Name" required>
          <Input value={uc.name} onChange={e => set('name', e.target.value)}
                 placeholder="e.g. Elephant Detection – Road Corridor" />
        </Field>
        <Field label="Description">
          <Textarea value={uc.description} onChange={e => set('description', e.target.value)}
                    placeholder="What does this scenario monitor and respond to?" />
        </Field>
        <Field label="Accent colour">
          <div className="flex items-center gap-2">
            <input type="color" value={uc.color} onChange={e => set('color', e.target.value)}
                   className="w-10 h-9 rounded border border-line cursor-pointer p-0.5" />
            <Input value={uc.color} onChange={e => set('color', e.target.value)} className="flex-1" />
          </div>
        </Field>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 2 — Devices
// ════════════════════════════════════════════════════════════════════════════

function StepDevices({ ucId, zoneId, devices, center, reload, guard }) {
  const [form, setForm] = useState({ name: '', type: 'camera' })
  const [placing, setPlacing] = useState(false)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  function place(latlng) {
    guard(async () => {
      await api('POST', '/api/devices', {
        name: form.name, type: form.type, use_case_id: ucId, zone_id: zoneId,
        lat: +latlng.lat.toFixed(6), lng: +latlng.lng.toFixed(6), online: true,
      })
      setForm({ name: '', type: 'camera' }); setPlacing(false)
      await reload()
    })
  }
  function remove(id) { guard(async () => { await api('DELETE', `/api/devices/${id}`); await reload() }) }

  return (
    <div>
      <StepHeading title="Add input devices"
        description="Cameras, thermal sensors, drones — whatever detects the target. Place each one on the map." />

      <div className="grid grid-cols-2 gap-2 items-end p-3 bg-surface-alt rounded-lg border border-line mb-4">
        <Field label="Device name">
          <Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Camera Trap – North Gate" />
        </Field>
        <Field label="Type">
          <Select value={form.type} onChange={e => set('type', e.target.value)}>
            {DEVICE_TYPES.map(t => <option key={t} value={t} className="capitalize">{t.replace('_', ' ')}</option>)}
          </Select>
        </Field>
        <div className="col-span-2">
          <Btn variant={placing ? 'secondary' : 'primary'} size="sm" disabled={!form.name.trim()}
               onClick={() => setPlacing(p => !p)}>
            <Crosshair size={13} /> {placing ? 'Click the map to drop it…' : 'Place on map'}
          </Btn>
        </div>
      </div>

      <WizardMap center={center} devices={devices} placing={placing} onPlace={place} height={320} />

      <DeviceList items={devices} onRemove={remove} />
    </div>
  )
}

function DeviceList({ items, onRemove }) {
  if (items.length === 0) return <p className="text-sm text-ink-muted mt-3">No devices yet.</p>
  return (
    <ul className="mt-3 space-y-1.5">
      {items.map(d => {
        const Icon = TYPE_ICON[d.type] || Camera
        return (
          <li key={d.id} className="flex items-center gap-2 px-3 py-2 bg-white border border-line rounded-lg text-sm">
            <Icon size={14} className="text-ink-muted" />
            <span className="text-ink font-medium">{d.name}</span>
            <span className="text-xs text-ink-muted capitalize">{d.type}</span>
            <span className="text-xs text-ink-muted ml-auto font-mono">{d.lat?.toFixed(4)}, {d.lng?.toFixed(4)}</span>
            <button onClick={() => onRemove(d.id)} className="text-ink-muted hover:text-sev-critical"><Trash2 size={13} /></button>
          </li>
        )
      })}
    </ul>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 3 — Road Signs
// ════════════════════════════════════════════════════════════════════════════

function StepSigns({ zoneId, devices, signs, center, reload, guard }) {
  const [form, setForm] = useState({ name: '', road: '', km_marker: '' })
  const [placing, setPlacing] = useState(false)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  function place(latlng) {
    guard(async () => {
      await api('POST', '/api/road-signs', {
        name: form.name, road: form.road, km_marker: Number(form.km_marker) || 0,
        zone_id: zoneId, lat: +latlng.lat.toFixed(6), lng: +latlng.lng.toFixed(6), online: true,
      })
      setForm({ name: '', road: '', km_marker: '' }); setPlacing(false)
      await reload()
    })
  }
  function remove(id) { guard(async () => { await api('DELETE', `/api/road-signs/${id}`); await reload() }) }

  return (
    <div>
      <StepHeading title="Add LED boards / road signs"
        description="The outputs that warn drivers. Devices are shown in blue for reference — place boards along the road." />

      <div className="grid grid-cols-3 gap-2 items-end p-3 bg-surface-alt rounded-lg border border-line mb-4">
        <Field label="Board name"><Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="LED Board 1" /></Field>
        <Field label="Road"><Input value={form.road} onChange={e => set('road', e.target.value)} placeholder="B43 Yala Road" /></Field>
        <Field label="km marker"><Input type="number" value={form.km_marker} onChange={e => set('km_marker', e.target.value)} placeholder="1.5" /></Field>
        <div className="col-span-3">
          <Btn variant={placing ? 'secondary' : 'primary'} size="sm" disabled={!form.name.trim()}
               onClick={() => setPlacing(p => !p)}>
            <Crosshair size={13} /> {placing ? 'Click the map to drop it…' : 'Place on map'}
          </Btn>
        </div>
      </div>

      <WizardMap center={center} devices={devices} signs={signs} placing={placing} onPlace={place} height={320} />

      {signs.length === 0 ? <p className="text-sm text-ink-muted mt-3">No boards yet.</p> : (
        <ul className="mt-3 space-y-1.5">
          {signs.map(s => (
            <li key={s.id} className="flex items-center gap-2 px-3 py-2 bg-white border border-line rounded-lg text-sm">
              <MapPin size={14} className="text-ink-muted" />
              <span className="text-ink font-medium">{s.name}</span>
              <span className="text-xs text-ink-muted">{s.road} · km {s.km_marker}</span>
              <span className="text-xs text-ink-muted ml-auto font-mono">{s.lat?.toFixed(4)}, {s.lng?.toFixed(4)}</span>
              <button onClick={() => remove(s.id)} className="text-ink-muted hover:text-sev-critical"><Trash2 size={13} /></button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 4 — Spatial Logic (with live preview)
// ════════════════════════════════════════════════════════════════════════════

function StepSpatial({ spatial, setSpatial, devices, signs, center }) {
  const [preview, setPreview] = useState(null)
  const set = (k, v) => setSpatial(s => ({ ...s, [k]: Number(v) }))

  const previewSigns = signs.map(s => ({
    ...s,
    state: preview
      ? (haversineM(preview.lat, preview.lng, s.lat, s.lng) <= spatial.propagation_radius_m ? 'WARNING' : 'CLEAR')
      : undefined,
  }))
  const litCount = preview ? previewSigns.filter(s => s.state === 'WARNING').length : 0

  return (
    <div>
      <StepHeading title="Spatial logic"
        description="How a detection lights nearby boards. Drop a test detection on the map to preview which boards react." />

      <div className="grid grid-cols-2 gap-4 mb-4">
        <Field label={`Propagation radius — ${spatial.propagation_radius_m} m`} hint="Boards within this distance of a detection light up">
          <input type="range" min="30" max="500" step="10" value={spatial.propagation_radius_m}
                 onChange={e => set('propagation_radius_m', e.target.value)} className="w-full accent-brand" />
        </Field>
        <Field label={`Min confidence — ${spatial.min_confidence}%`} hint="Ignore detections weaker than this">
          <input type="range" min="0" max="95" step="5" value={spatial.min_confidence}
                 onChange={e => set('min_confidence', e.target.value)} className="w-full accent-brand" />
        </Field>
        <Field label="RED hold (seconds)" hint="Stays RED this long after last detection">
          <Input type="number" value={spatial.red_hold_s} onChange={e => set('red_hold_s', e.target.value)} />
        </Field>
        <Field label="AMBER hold (seconds)" hint="Fades to GREEN after this; AMBER in between">
          <Input type="number" value={spatial.amber_hold_s} onChange={e => set('amber_hold_s', e.target.value)} />
        </Field>
      </div>

      <div className="flex items-center justify-between mb-2">
        <Btn variant={preview ? 'secondary' : 'primary'} size="sm"
             onClick={() => setPreview(p => p ? null : 'arm')}>
          <Crosshair size={13} /> {preview ? 'Clear preview' : 'Drop test detection'}
        </Btn>
        {preview && preview !== 'arm' && (
          <span className="text-sm text-ink-muted">
            <span className="text-sev-critical font-semibold">{litCount}</span> board(s) would light RED
          </span>
        )}
        {preview === 'arm' && <span className="text-xs text-orange">Click the map to place the test detection…</span>}
      </div>

      <WizardMap
        center={center} devices={devices} signs={previewSigns}
        placing={preview === 'arm'}
        onPlace={(latlng) => setPreview({ lat: latlng.lat, lng: latlng.lng })}
        preview={preview && preview !== 'arm' ? { ...preview, radius: spatial.propagation_radius_m } : null}
        height={340}
      />

      <div className="mt-3 p-3 bg-surface rounded-lg text-xs text-ink-muted leading-relaxed">
        <strong className="text-ink">How it works:</strong> a detection lights every board within the radius.
        Each board shows <span className="text-sev-critical font-medium">RED</span> for the RED-hold window, fades to
        <span className="text-orange font-medium"> AMBER</span>, then <span className="text-sev-low font-medium">GREEN</span>.
        A moving animal makes the lit zone travel along the road automatically.
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 5 — Notifications (stakeholders + rule)
// ════════════════════════════════════════════════════════════════════════════

function StepNotify({ ucId, stakeholders, rules, signs, reload, guard }) {
  return (
    <div className="space-y-8">
      <StepHeading title="Notifications & rules"
        description="Who gets alerted, and the rule that decides when an incident fires." />
      <StakeholderSection {...{ ucId, stakeholders, reload, guard }} />
      <RuleSection {...{ ucId, stakeholders, rules, reload, guard }} />
    </div>
  )
}

function StakeholderSection({ ucId, stakeholders, reload, guard }) {
  const [form, setForm] = useState({ name: '', role: '', chType: 'sms', address: '' })
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  function add() {
    guard(async () => {
      if (!form.name.trim() || !form.address.trim()) throw new Error('Stakeholder needs a name and a contact address')
      await api('POST', '/api/stakeholders', {
        name: form.name, role: form.role, use_case_ids: [ucId], on_call: true,
        channels: [{ type: form.chType, address: form.address, language: 'en' }],
      })
      setForm({ name: '', role: '', chType: 'sms', address: '' })
      await reload()
    })
  }
  function remove(id) { guard(async () => { await api('DELETE', `/api/stakeholders/${id}`); await reload() }) }

  return (
    <section>
      <h3 className="font-semibold text-ink mb-2">Stakeholders</h3>
      <div className="grid grid-cols-4 gap-2 items-end p-3 bg-surface-alt rounded-lg border border-line">
        <Field label="Name"><Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Park Warden" /></Field>
        <Field label="Role"><Input value={form.role} onChange={e => set('role', e.target.value)} placeholder="Wildlife Officer" /></Field>
        <Field label="Channel">
          <Select value={form.chType} onChange={e => set('chType', e.target.value)}>
            {CHANNEL_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select>
        </Field>
        <Field label="Address">
          <div className="flex gap-2">
            <Input value={form.address} onChange={e => set('address', e.target.value)}
                   placeholder={form.chType === 'email' ? 'a@b.lk' : '+9477…'} onKeyDown={e => e.key === 'Enter' && add()} />
            <Btn variant="secondary" size="sm" onClick={add}>Add</Btn>
          </div>
        </Field>
      </div>
      {stakeholders.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {stakeholders.map(s => (
            <li key={s.id} className="flex items-center gap-2 px-3 py-2 bg-white border border-line rounded-lg text-sm">
              <span className="text-ink font-medium">{s.name}</span>
              <span className="text-xs text-ink-muted">{s.role}</span>
              <span className="ml-auto flex gap-1">{(s.channels || []).map((c, i) => <Badge key={i}>{c.type}</Badge>)}</span>
              <button onClick={() => remove(s.id)} className="text-ink-muted hover:text-sev-critical"><Trash2 size={13} /></button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function RuleSection({ ucId, stakeholders, rules, reload, guard }) {
  const [r, setR] = useState({
    object: 'elephant', minConf: 60, severity: 'HIGH', notify: [],
    confirm: false, count: 2, windowMin: 15, confirmSeverity: 'CRITICAL', confirmNotify: [],
  })
  const set = (k, v) => setR(s => ({ ...s, [k]: v }))
  const toggle = (key, id) => setR(s => ({ ...s, [key]: s[key].includes(id) ? s[key].filter(x => x !== id) : [...s[key], id] }))

  function create() {
    guard(async () => {
      if (r.notify.length === 0) throw new Error('Pick at least one stakeholder to notify on trigger')
      const actions = {
        on_trigger: {
          create_incident: true, incident_severity: r.severity, notify_stakeholder_ids: r.notify,
          actuate_sign_ids: [], sign_state: 'CAUTION',
          message_template: `[${r.severity}] ${r.object} detected in {zone_name} ({device_name}). Confidence {confidence}%. Incident {incident_id}`,
        },
      }
      if (r.confirm) {
        actions.on_confirm = {
          create_incident: true, incident_severity: r.confirmSeverity,
          notify_stakeholder_ids: r.confirmNotify.length ? r.confirmNotify : r.notify,
          actuate_sign_ids: [], sign_state: 'WARNING',
          message_template: `[${r.confirmSeverity}] CONFIRMED ${r.object} on {zone_name}. Multiple detections. Incident {incident_id}`,
        }
      }
      await api('POST', '/api/rules', {
        use_case_id: ucId, name: `${r.object} ${r.confirm ? 'detection + confirmation' : 'detection'}`,
        description: `Auto-created by setup wizard`, priority: r.confirm ? 2 : 1, active: true,
        conditions: [
          { field: 'object_type', op: 'eq', value: r.object },
          { field: 'confidence', op: 'gte', value: Number(r.minConf) },
        ],
        confirmation: r.confirm ? { required_count: Number(r.count), window_seconds: Number(r.windowMin) * 60, same_zone: true } : null,
        actions,
      })
      await reload()
    })
  }

  return (
    <section>
      <h3 className="font-semibold text-ink mb-2">Detection rule</h3>
      <div className="p-4 bg-surface-alt rounded-lg border border-line space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <Field label="Object type"><Input value={r.object} onChange={e => set('object', e.target.value)} /></Field>
          <Field label="Min confidence %"><Input type="number" value={r.minConf} onChange={e => set('minConf', e.target.value)} /></Field>
          <Field label="Severity on trigger">
            <Select value={r.severity} onChange={e => set('severity', e.target.value)}>
              {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map(s => <option key={s}>{s}</option>)}
            </Select>
          </Field>
        </div>

        <Field label="Notify on trigger">
          <StakeholderChecks items={stakeholders} selected={r.notify} onToggle={id => toggle('notify', id)} />
        </Field>

        <label className="flex items-center gap-2 text-sm text-ink cursor-pointer">
          <input type="checkbox" checked={r.confirm} onChange={e => set('confirm', e.target.checked)} className="rounded border-line accent-brand" />
          Escalate when multiple detections confirm (reduces false alarms)
        </label>

        {r.confirm && (
          <div className="pl-6 space-y-3 border-l-2 border-line">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Detections needed"><Input type="number" min="2" value={r.count} onChange={e => set('count', e.target.value)} /></Field>
              <Field label="Within (minutes)"><Input type="number" min="1" value={r.windowMin} onChange={e => set('windowMin', e.target.value)} /></Field>
              <Field label="Escalated severity">
                <Select value={r.confirmSeverity} onChange={e => set('confirmSeverity', e.target.value)}>
                  {['MEDIUM', 'HIGH', 'CRITICAL'].map(s => <option key={s}>{s}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="Notify on confirmation (defaults to trigger list)">
              <StakeholderChecks items={stakeholders} selected={r.confirmNotify} onToggle={id => toggle('confirmNotify', id)} />
            </Field>
          </div>
        )}

        <Btn variant="secondary" size="sm" onClick={create} disabled={stakeholders.length === 0}>
          <Plus size={13} /> Create rule
        </Btn>
      </div>

      {rules.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {rules.map(rule => (
            <li key={rule.id} className="flex items-center gap-2 px-3 py-2 bg-white border border-line rounded-lg text-sm">
              <CheckCircle size={14} className="text-sev-low" />
              <span className="text-ink font-medium">{rule.name}</span>
              {rule.confirmation && <Badge color="amber">confirm ×{rule.confirmation.required_count}</Badge>}
              <span className="ml-auto text-xs text-ink-muted">priority {rule.priority}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function StakeholderChecks({ items, selected, onToggle }) {
  if (items.length === 0) return <p className="text-xs text-ink-muted">Add stakeholders above first.</p>
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(s => (
        <label key={s.id} className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs cursor-pointer transition-colors
          ${selected.includes(s.id) ? 'bg-brand/10 border-brand text-brand' : 'border-line text-ink-muted hover:bg-surface-alt'}`}>
          <input type="checkbox" checked={selected.includes(s.id)} onChange={() => onToggle(s.id)} className="hidden" />
          {s.name}
        </label>
      ))}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 6 — Review
// ════════════════════════════════════════════════════════════════════════════

function StepReview({ uc, spatial, devices, signs, stakeholders, rules }) {
  return (
    <div>
      <StepHeading title="Review & activate"
        description="Confirm everything looks right, then activate. You can keep editing later in the admin pages." />

      <div className="grid grid-cols-2 gap-4">
        <SummaryCard label="Use case" value={uc.name} sub={uc.description} accent={uc.color} />
        <SummaryCard label="Spatial" value={`${spatial.propagation_radius_m} m radius`}
          sub={`RED ${spatial.red_hold_s}s · AMBER ${spatial.amber_hold_s}s · min ${spatial.min_confidence}%`} />
        <SummaryCard label="Input devices" value={`${devices.length}`} sub={devices.map(d => d.name).join(', ')} />
        <SummaryCard label="LED boards" value={`${signs.length}`} sub={signs.map(s => s.name).join(', ')} />
        <SummaryCard label="Stakeholders" value={`${stakeholders.length}`} sub={stakeholders.map(s => s.name).join(', ')} />
        <SummaryCard label="Rules" value={`${rules.length}`} sub={rules.map(r => r.name).join(', ')} />
      </div>

      <div className="mt-5 p-4 rounded-lg bg-sev-low/5 border border-sev-low/20 flex items-start gap-3">
        <Rocket size={16} className="text-sev-low mt-0.5 shrink-0" />
        <p className="text-sm text-ink-muted">
          Activating marks the use case live. Open <strong className="text-ink">Road Signs → Map → Simulate detection</strong>
          {' '}to watch boards light up, or use the phone camera page to trigger a real detection.
        </p>
      </div>
    </div>
  )
}

function SummaryCard({ label, value, sub, accent }) {
  return (
    <div className="p-4 rounded-lg border border-line bg-white">
      <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide flex items-center gap-2">
        {accent && <span className="w-2 h-2 rounded-full" style={{ background: accent }} />}{label}
      </div>
      <div className="text-lg font-semibold text-ink mt-1">{value || '—'}</div>
      {sub && <div className="text-xs text-ink-muted mt-0.5 line-clamp-2">{sub}</div>}
    </div>
  )
}
