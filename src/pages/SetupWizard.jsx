import { useState, useCallback, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Rocket, Plus, Trash2, MapPin, Camera, Thermometer, Plane, Radio, Activity,
  Crosshair, CheckCircle, X, FlaskConical, ChevronLeft, ChevronRight,
} from 'lucide-react'
import {
  Panel, Field, Input, Select, Textarea, Button, Badge, Banner,
  Stepper, Checkbox, ToastStack,
} from '../components/ui'
import WizardMap from '../components/wizard/WizardMap.jsx'
import { simulateEvent } from '../lib/sim.js'
import { haversineM } from '../lib/geo.js'
import { useToast } from '../hooks/useToast.js'

const STEPS = [
  { label: 'Scenario', sublabel: 'what & where' },
  { label: 'Sensors',  sublabel: 'inputs' },
  { label: 'Signs',    sublabel: 'outputs' },
  { label: 'Response', sublabel: 'rules & alerts' },
  { label: 'Review',   sublabel: 'test & activate' },
]

const DEVICE_TYPES = ['camera', 'thermal', 'drone', 'acoustic', 'pressure_pad', 'manual']
const TYPE_ICON = { camera: Camera, thermal: Thermometer, drone: Plane, acoustic: Radio, pressure_pad: Activity, manual: Activity }
const CHANNEL_TYPES = ['sms', 'whatsapp', 'email']
const DEFAULT_SPATIAL = { mode: 'radius', propagation_radius_m: 120, red_hold_s: 90, amber_hold_s: 420, min_confidence: 55 }
const DEFAULT_CENTER = [6.3818, 81.48]

async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try { msg = (await res.json()).detail || msg } catch {}
    throw new Error(msg)
  }
  return res.status === 204 ? null : res.json()
}


// ── two-column step frame ──────────────────────────────────────────────────────
function StepLayout({ title, description, children, map }) {
  return (
    <div className="flex h-full overflow-hidden">
      <div className="w-[440px] shrink-0 overflow-y-auto bg-white border-r border-line">
        <div className="p-6">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          {description && <p className="text-sm text-ink-muted mt-1">{description}</p>}
          <div className="mt-5 space-y-5">{children}</div>
        </div>
      </div>
      <div className="flex-1 relative bg-surface-sunken">{map}</div>
    </div>
  )
}

export default function SetupWizard() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { toasts, addToast, removeToast } = useToast()

  const [step, setStep]             = useState(0)
  const [maxReached, setMaxReached] = useState(0)
  const [busy, setBusy]             = useState(false)
  const [error, setError]           = useState(null)

  const [ucId, setUcId]     = useState(null)
  const [zoneId, setZoneId] = useState(null)

  const [scenario, setScenario] = useState({ name: '', description: '', color: '#D92D20', objectTypes: [], location: null })
  const [spatial, setSpatial]   = useState(DEFAULT_SPATIAL)

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

  // Resume an in-progress (inactive) use case via ?uc=ID.
  useEffect(() => {
    const id = searchParams.get('uc')
    if (!id) return
    ;(async () => {
      try {
        const uc = await api('GET', `/api/use-cases/${id}`)
        const zones = await api('GET', '/api/zones')
        const zone = zones.find(z => z.use_case_id === id)
        setUcId(id); setZoneId(zone?.id)
        setScenario({
          name: uc.name || '', description: uc.description || '', color: uc.color || '#D92D20',
          objectTypes: uc.object_types || [],
          location: zone ? { lat: zone.lat, lng: zone.lng, label: zone.name } : null,
        })
        setSpatial(uc.spatial || DEFAULT_SPATIAL)
        const [devs, sgs, shs, rls] = await Promise.all([
          api('GET', '/api/devices'), api('GET', '/api/road-signs'),
          api('GET', '/api/stakeholders'), api('GET', '/api/rules'),
        ])
        setDevices(devs.filter(d => d.use_case_id === id))
        setSigns(sgs.filter(s => s.zone_id === zone?.id))
        setStakeholders(shs.filter(s => (s.use_case_ids || []).includes(id)))
        setRules(rls.filter(r => r.use_case_id === id))
        setStep(1); setMaxReached(4)
      } catch (e) { setError(e.message) }
    })()
  }, [])  // eslint-disable-line

  function goTo(i) { setStep(i); setMaxReached(m => Math.max(m, i)); setError(null) }
  async function guard(fn) {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(e.message || String(e)) } finally { setBusy(false) }
  }

  const center = scenario.location ? [scenario.location.lat, scenario.location.lng]
    : devices[0]?.lat != null ? [devices[0].lat, devices[0].lng] : DEFAULT_CENTER
  const zoneMarker = scenario.location ? { ...scenario.location, name: `${scenario.name || 'Scenario'} area` } : null

  async function commitScenario() {
    await guard(async () => {
      if (!scenario.name.trim()) throw new Error('Give your scenario a name')
      if (!scenario.location)    throw new Error('Set a location — search or click the map')
      const zoneName = `${scenario.name.trim()} area`
      const ucBody = { name: scenario.name.trim(), description: scenario.description, color: scenario.color, object_types: scenario.objectTypes, spatial }
      if (ucId) {
        await api('PUT', `/api/use-cases/${ucId}`, ucBody)
        await api('PUT', `/api/zones/${zoneId}`, { name: zoneName, lat: scenario.location.lat, lng: scenario.location.lng })
        await reload()
      } else {
        const created = await api('POST', '/api/use-cases', { ...ucBody, active: false })
        const zone = await api('POST', '/api/zones', { name: zoneName, use_case_id: created.id, lat: scenario.location.lat, lng: scenario.location.lng })
        setUcId(created.id); setZoneId(zone.id)
        await reload(created.id, zone.id)
      }
      goTo(1)
    })
  }
  async function commitSpatial() { await guard(async () => { await api('PUT', `/api/use-cases/${ucId}`, { spatial }) }) }
  async function activate() {
    await guard(async () => { await api('PUT', `/api/use-cases/${ucId}`, { active: true, spatial }); navigate('/road-signs') })
  }

  const common = { ucId, zoneId, center, zoneMarker, devices, signs, stakeholders, rules, spatial, scenario, reload, guard, addToast }

  // footer config per step
  const footer = [
    { back: null, next: commitScenario, nextLabel: 'Next', disabled: !scenario.name.trim() || !scenario.location, hint: 'Creates the scenario and its zone' },
    { back: () => goTo(0), next: () => goTo(2), nextLabel: 'Next', disabled: devices.length === 0, hint: devices.length === 0 ? 'Add at least one sensor' : `${devices.length} sensor(s)` },
    { back: () => goTo(1), next: () => goTo(3), nextLabel: signs.length === 0 ? 'Skip — no signs' : 'Next', disabled: false, hint: signs.length === 0 ? 'Optional for notification-only scenarios' : `${signs.length} board(s)` },
    { back: () => goTo(2), next: async () => { await commitSpatial(); goTo(4) }, nextLabel: 'Next', disabled: stakeholders.length === 0 || rules.length === 0, hint: stakeholders.length === 0 ? 'Add a stakeholder' : rules.length === 0 ? 'Create a rule' : 'Ready to review' },
    { back: () => goTo(3), next: activate, nextLabel: 'Activate scenario', disabled: false, hint: 'Marks the scenario live' },
  ][step]

  return (
    <div className="h-screen flex flex-col bg-surface overflow-hidden">
      {/* Focused wizard header (no dashboard nav) */}
      <header className="h-14 bg-maroon flex items-center px-4 gap-3 shrink-0 z-nav">
        <div className="w-7 h-7 bg-brand rounded flex items-center justify-center text-white font-bold text-sm">D</div>
        <span className="text-white font-semibold text-sm flex items-center gap-2"><Rocket size={15} /> Setup Wizard</span>
        <button onClick={() => navigate('/incidents')}
                className="ml-auto flex items-center gap-1.5 text-white/80 hover:text-white text-sm">
          <X size={16} /> Exit
        </button>
      </header>

      {/* Stepper */}
      <div className="px-6 py-3 border-b border-line bg-white shrink-0 overflow-x-auto">
        <Stepper steps={STEPS} current={step} maxReached={maxReached} onStepClick={goTo} />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden relative">
        {error && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1200] w-[420px]">
            <Banner variant="error">{error}</Banner>
          </div>
        )}
        {step === 0 && <StepScenario scenario={scenario} setScenario={setScenario} center={center} zoneMarker={zoneMarker} />}
        {step === 1 && <StepSensors {...common} />}
        {step === 2 && <StepSigns {...common} />}
        {step === 3 && <StepResponse {...common} setSpatial={setSpatial} />}
        {step === 4 && <StepReview {...common} />}
      </div>

      {/* Footer */}
      <div className="border-t border-line bg-white px-6 py-3 flex items-center justify-between shrink-0">
        <div className="text-xs text-ink-muted">{footer.hint}</div>
        <div className="flex gap-3">
          {footer.back && <Button variant="secondary" onClick={footer.back} disabled={busy}><ChevronLeft size={15} /> Back</Button>}
          <Button variant="primary" onClick={footer.next} disabled={footer.disabled} loading={busy}>
            {footer.nextLabel} <ChevronRight size={15} />
          </Button>
        </div>
      </div>

      <ToastStack toasts={toasts} onRemove={removeToast} />
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 1 — Scenario
// ════════════════════════════════════════════════════════════════════════════
function StepScenario({ scenario, setScenario, center, zoneMarker }) {
  const set = (k, v) => setScenario(s => ({ ...s, [k]: v }))
  const [objInput, setObjInput] = useState('')
  function addObject() {
    const v = objInput.trim().toLowerCase()
    if (v && !scenario.objectTypes.includes(v)) set('objectTypes', [...scenario.objectTypes, v])
    setObjInput('')
  }
  return (
    <StepLayout title="Name your scenario"
      description="What you're detecting and where. This becomes the use case and its zone."
      map={<WizardMap bare center={center} zoom={scenario.location ? 14 : 6} zone={zoneMarker} searchable placing
             onSearchPick={(p) => set('location', p)}
             onPlace={(latlng) => set('location', { lat: +latlng.lat.toFixed(6), lng: +latlng.lng.toFixed(6), label: `${latlng.lat.toFixed(4)}, ${latlng.lng.toFixed(4)}` })} />}>
      <Field label="Scenario name" required>
        <Input value={scenario.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Elephant Detection – Yala" />
      </Field>
      <Field label="What are you detecting?" hint="Press Enter to add. Drives the detection rule.">
        <div className="flex gap-2">
          <Input value={objInput} onChange={e => setObjInput(e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addObject() } }} placeholder="elephant, vehicle, fire…" />
          <Button variant="secondary" size="sm" onClick={addObject}>Add</Button>
        </div>
        {scenario.objectTypes.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {scenario.objectTypes.map(o => (
              <span key={o} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs bg-brand-subtle text-brand font-medium">
                {o}<button onClick={() => set('objectTypes', scenario.objectTypes.filter(x => x !== o))}><X size={11} /></button>
              </span>
            ))}
          </div>
        )}
      </Field>
      <Field label="Description"><Textarea value={scenario.description} onChange={e => set('description', e.target.value)} placeholder="What does this scenario monitor?" /></Field>
      <Field label="Location" required hint={scenario.location ? scenario.location.label : 'Search or click the map →'}>
        <div className="flex items-center gap-2 text-sm">
          <MapPin size={15} className={scenario.location ? 'text-sev-low' : 'text-ink-subtle'} />
          <span className={scenario.location ? 'text-ink' : 'text-ink-muted'}>
            {scenario.location ? `${scenario.location.lat.toFixed(4)}, ${scenario.location.lng.toFixed(4)}` : 'No location set'}
          </span>
        </div>
      </Field>
      <Field label="Accent colour">
        <div className="flex items-center gap-2">
          <input type="color" value={scenario.color} onChange={e => set('color', e.target.value)} className="w-10 h-9 rounded border border-line cursor-pointer p-0.5" />
          <Input value={scenario.color} onChange={e => set('color', e.target.value)} className="flex-1" />
        </div>
      </Field>
    </StepLayout>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 2 — Sensors  (managed list + add button; one device = one marker)
// ════════════════════════════════════════════════════════════════════════════
function StepSensors({ ucId, zoneId, center, zoneMarker, devices, reload, guard }) {
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'camera' })
  const [placingId, setPlacingId] = useState(null)   // device id awaiting a click
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  async function addDevice(thenPlace) {
    await guard(async () => {
      const created = await api('POST', '/api/devices', {
        name: form.name.trim() || `Sensor ${devices.length + 1}`, type: form.type,
        use_case_id: ucId, zone_id: zoneId, online: true,
      })
      setForm({ name: '', type: form.type }); setAdding(false); await reload()
      if (thenPlace) setPlacingId(created.id)
    })
  }
  async function placeAt(latlng) {
    if (!placingId) return
    await guard(async () => {
      await api('PUT', `/api/devices/${placingId}`, { lat: +latlng.lat.toFixed(6), lng: +latlng.lng.toFixed(6) })
      setPlacingId(null); await reload()
    })
  }
  function remove(id) { guard(async () => { await api('DELETE', `/api/devices/${id}`); if (placingId === id) setPlacingId(null); await reload() }) }

  const placingDevice = devices.find(d => d.id === placingId)

  return (
    <StepLayout title="Add your sensors"
      description="Cameras, thermal sensors, drones — whatever detects the target. One sensor, one marker."
      map={<WizardMap bare center={center} zoom={14} zone={zoneMarker} devices={devices}
             placing={!!placingId} onPlace={placeAt} />}>

      {placingId && (
        <Banner variant="info">Click the map to place <strong>{placingDevice?.name}</strong>.</Banner>
      )}

      <ItemList items={devices} kind="sensor" onRemove={remove} onPlace={(id) => setPlacingId(id)} placingId={placingId} />

      {adding ? (
        <Panel title="New sensor">
          <div className="space-y-3">
            <Field label="Name"><Input autoFocus value={form.name} onChange={e => set('name', e.target.value)} placeholder="Camera Trap 1" /></Field>
            <Field label="Type">
              <Select value={form.type} onChange={e => set('type', e.target.value)}>
                {DEVICE_TYPES.map(t => <option key={t} value={t} className="capitalize">{t.replace('_', ' ')}</option>)}
              </Select>
            </Field>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" onClick={() => addDevice(true)}><Crosshair size={13} /> Add &amp; place on map</Button>
              <Button size="sm" variant="secondary" onClick={() => addDevice(false)}>Add unplaced</Button>
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          </div>
        </Panel>
      ) : (
        <Button variant="secondary" onClick={() => setAdding(true)} className="w-full justify-center"><Plus size={14} /> Add sensor</Button>
      )}
    </StepLayout>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 3 — Signs
// ════════════════════════════════════════════════════════════════════════════
function StepSigns({ ucId, zoneId, center, zoneMarker, devices, signs, spatial, reload, guard }) {
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', road: '' })
  const [placingId, setPlacingId] = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const radius = Number(spatial.propagation_radius_m) || 120

  async function addSign(thenPlace) {
    await guard(async () => {
      const created = await api('POST', '/api/road-signs', {
        name: form.name.trim() || `Board ${signs.length + 1}`, road: form.road, zone_id: zoneId, online: true,
      })
      setForm({ name: '', road: form.road }); setAdding(false); await reload()
      if (thenPlace) setPlacingId(created.id)
    })
  }
  async function placeAt(latlng) {
    if (!placingId) return
    await guard(async () => {
      await api('PUT', `/api/road-signs/${placingId}`, { lat: +latlng.lat.toFixed(6), lng: +latlng.lng.toFixed(6) })
      setPlacingId(null); await reload()
    })
  }
  function remove(id) { guard(async () => { await api('DELETE', `/api/road-signs/${id}`); if (placingId === id) setPlacingId(null); await reload() }) }

  const placingSign = signs.find(s => s.id === placingId)
  const uncovered = signs.filter(s => s.lat != null && !devices.some(d => d.lat != null && haversineM(s.lat, s.lng, d.lat, d.lng) <= radius))

  return (
    <StepLayout title="Add your signs"
      description="LED boards that warn people. The blue rings show sensor reach — place boards inside a ring so they light. Optional."
      map={<WizardMap bare center={center} zoom={14} zone={zoneMarker} devices={devices} signs={signs} showRings radius={radius}
             placing={!!placingId} onPlace={placeAt} />}>

      {placingId && <Banner variant="info">Click the map to place <strong>{placingSign?.name}</strong>.</Banner>}
      {uncovered.length > 0 && (
        <Banner variant="warning">{uncovered.length} board{uncovered.length > 1 ? 's' : ''} outside all sensor coverage — they won't light. Move them inside a ring or widen the radius.</Banner>
      )}

      <ItemList items={signs} kind="sign" onRemove={remove} onPlace={(id) => setPlacingId(id)} placingId={placingId} />

      {adding ? (
        <Panel title="New sign board">
          <div className="space-y-3">
            <Field label="Name"><Input autoFocus value={form.name} onChange={e => set('name', e.target.value)} placeholder="LED Board 1" /></Field>
            <Field label="Road"><Input value={form.road} onChange={e => set('road', e.target.value)} placeholder="B43 Yala Road" /></Field>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" onClick={() => addSign(true)}><Crosshair size={13} /> Add &amp; place on map</Button>
              <Button size="sm" variant="secondary" onClick={() => addSign(false)}>Add unplaced</Button>
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          </div>
        </Panel>
      ) : (
        <Button variant="secondary" onClick={() => setAdding(true)} className="w-full justify-center"><Plus size={14} /> Add sign board</Button>
      )}
    </StepLayout>
  )
}

function ItemList({ items, kind, onRemove, onPlace, placingId }) {
  if (items.length === 0) return <p className="text-sm text-ink-muted">No {kind}s yet — add one below.</p>
  return (
    <ul className="space-y-1.5">
      {items.map(d => {
        const Icon = kind === 'sensor' ? (TYPE_ICON[d.type] || Camera) : MapPin
        const placed = d.lat != null && d.lng != null
        return (
          <li key={d.id} className={`flex items-center gap-2 px-3 py-2 bg-white border rounded-lg text-sm
            ${placingId === d.id ? 'border-brand ring-1 ring-brand/30' : 'border-line'}`}>
            <Icon size={14} className="text-ink-muted shrink-0" />
            <div className="min-w-0">
              <div className="text-ink font-medium truncate">{d.name}</div>
              <div className="text-xs text-ink-muted">
                {kind === 'sensor' ? d.type : d.road || 'board'}
                {placed && <span className="font-mono"> · {d.lat.toFixed(4)}, {d.lng.toFixed(4)}</span>}
              </div>
            </div>
            <div className="ml-auto flex items-center gap-1 shrink-0">
              {placed
                ? <button onClick={() => onPlace(d.id)} className="text-xs text-brand hover:underline">Move</button>
                : <button onClick={() => onPlace(d.id)} className="inline-flex items-center gap-1 text-xs text-brand hover:underline"><Crosshair size={11} /> Place</button>}
              <button onClick={() => onRemove(d.id)} className="text-ink-muted hover:text-sev-critical ml-1"><Trash2 size={13} /></button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 4 — Response
// ════════════════════════════════════════════════════════════════════════════
function StepResponse({ ucId, scenario, stakeholders, rules, reload, guard, spatial, setSpatial, devices, signs, center, zoneMarker }) {
  const [preview, setPreview] = useState(null)
  const radius = Number(spatial.propagation_radius_m) || 120
  const previewSigns = signs.map(s => ({
    ...s, state: preview && preview !== 'arm' ? (haversineM(preview.lat, preview.lng, s.lat, s.lng) <= radius ? 'WARNING' : 'CLEAR') : undefined,
  }))

  return (
    <StepLayout title="What happens on a detection?"
      description="Who's alerted, the rule that opens an incident, and how signs light up."
      map={<WizardMap bare center={center} zoom={14} zone={zoneMarker} devices={devices} signs={previewSigns} showRings radius={radius}
             placing={preview === 'arm'} onPlace={(latlng) => setPreview({ lat: latlng.lat, lng: latlng.lng })}
             preview={preview && preview !== 'arm' ? { ...preview, radius } : null} />}>
      <StakeholderSection {...{ ucId, stakeholders, reload, guard }} />
      <RuleSection {...{ ucId, scenario, stakeholders, rules, reload, guard }} />
      <SpatialSection {...{ spatial, setSpatial, preview, setPreview, signs }} />
    </StepLayout>
  )
}

function StakeholderSection({ ucId, stakeholders, reload, guard }) {
  const [form, setForm] = useState({ name: '', role: '', chType: 'sms', address: '' })
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  function add() {
    guard(async () => {
      if (!form.name.trim() || !form.address.trim()) throw new Error('Stakeholder needs a name and a contact address')
      await api('POST', '/api/stakeholders', { name: form.name, role: form.role, use_case_ids: [ucId], on_call: true, channels: [{ type: form.chType, address: form.address, language: 'en' }] })
      setForm({ name: '', role: '', chType: 'sms', address: '' }); await reload()
    })
  }
  function remove(id) { guard(async () => { await api('DELETE', `/api/stakeholders/${id}`); await reload() }) }
  return (
    <Panel title="Stakeholders to alert">
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Name" />
          <Input value={form.role} onChange={e => set('role', e.target.value)} placeholder="Role" />
        </div>
        <div className="flex gap-2">
          <Select value={form.chType} onChange={e => set('chType', e.target.value)} className="w-28">
            {CHANNEL_TYPES.map(c => <option key={c} value={c} className="capitalize">{c}</option>)}
          </Select>
          <Input value={form.address} onChange={e => set('address', e.target.value)} placeholder={form.chType === 'email' ? 'a@b.lk' : '+9477…'} onKeyDown={e => e.key === 'Enter' && add()} />
          <Button variant="secondary" size="sm" onClick={add}>Add</Button>
        </div>
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
    </Panel>
  )
}

function RuleSection({ ucId, scenario, stakeholders, rules, reload, guard }) {
  const [r, setR] = useState({ object: scenario.objectTypes[0] || 'object', minConf: 60, severity: 'HIGH', notify: [], confirm: false, count: 2, windowMin: 15, confirmSeverity: 'CRITICAL', confirmNotify: [] })
  const set = (k, v) => setR(s => ({ ...s, [k]: v }))
  const toggle = (key, id) => setR(s => ({ ...s, [key]: s[key].includes(id) ? s[key].filter(x => x !== id) : [...s[key], id] }))
  function create() {
    guard(async () => {
      if (r.notify.length === 0) throw new Error('Pick at least one stakeholder to notify')
      const actions = { on_trigger: { create_incident: true, incident_severity: r.severity, notify_stakeholder_ids: r.notify, message_template: `[${r.severity}] ${r.object} detected in {zone_name} ({device_name}). Confidence {confidence}%. Incident {incident_id}` } }
      if (r.confirm) actions.on_confirm = { create_incident: true, incident_severity: r.confirmSeverity, notify_stakeholder_ids: r.confirmNotify.length ? r.confirmNotify : r.notify, message_template: `[${r.confirmSeverity}] CONFIRMED ${r.object} on {zone_name}. Incident {incident_id}` }
      await api('POST', '/api/rules', {
        use_case_id: ucId, name: `${r.object} ${r.confirm ? 'detection + confirmation' : 'detection'}`, description: 'Created by setup wizard',
        priority: r.confirm ? 2 : 1, active: true,
        conditions: [{ field: 'object_type', op: 'eq', value: r.object }, { field: 'confidence', op: 'gte', value: Number(r.minConf) }],
        confirmation: r.confirm ? { required_count: Number(r.count), window_seconds: Number(r.windowMin) * 60, same_zone: true } : null, actions,
      })
      await reload()
    })
  }
  return (
    <Panel title="Detection rule">
      <div className="space-y-3">
        <Field label="Object type" hint="Must match what sensors report">
          <Input value={r.object} onChange={e => set('object', e.target.value)} list="obj-suggest" />
          <datalist id="obj-suggest">{scenario.objectTypes.map(o => <option key={o} value={o} />)}</datalist>
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Min confidence %"><Input type="number" value={r.minConf} onChange={e => set('minConf', e.target.value)} /></Field>
          <Field label="Severity"><Select value={r.severity} onChange={e => set('severity', e.target.value)}>{['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map(s => <option key={s}>{s}</option>)}</Select></Field>
        </div>
        <Field label="Notify on trigger"><StakeholderChecks items={stakeholders} selected={r.notify} onToggle={id => toggle('notify', id)} /></Field>
        <Checkbox label="Escalate when multiple detections confirm" checked={r.confirm} onChange={e => set('confirm', e.target.checked)} />
        {r.confirm && (
          <div className="pl-3 border-l-2 border-line space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Detections"><Input type="number" min="2" value={r.count} onChange={e => set('count', e.target.value)} /></Field>
              <Field label="Within (min)"><Input type="number" min="1" value={r.windowMin} onChange={e => set('windowMin', e.target.value)} /></Field>
            </div>
            <Field label="Escalated severity"><Select value={r.confirmSeverity} onChange={e => set('confirmSeverity', e.target.value)}>{['MEDIUM', 'HIGH', 'CRITICAL'].map(s => <option key={s}>{s}</option>)}</Select></Field>
          </div>
        )}
        <Button variant="secondary" size="sm" onClick={create} disabled={stakeholders.length === 0}><Plus size={13} /> Create rule</Button>
      </div>
      {rules.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {rules.map(rule => (
            <li key={rule.id} className="flex items-center gap-2 px-3 py-2 bg-white border border-line rounded-lg text-sm">
              <CheckCircle size={14} className="text-sev-low" /><span className="text-ink font-medium">{rule.name}</span>
              {rule.confirmation && <Badge color="amber">×{rule.confirmation.required_count}</Badge>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function SpatialSection({ spatial, setSpatial, preview, setPreview, signs }) {
  const set = (k, v) => setSpatial(s => ({ ...s, [k]: Number(v) }))
  const radius = Number(spatial.propagation_radius_m) || 120
  const litCount = preview && preview !== 'arm' ? signs.filter(s => s.lat != null && haversineM(preview.lat, preview.lng, s.lat, s.lng) <= radius).length : 0
  return (
    <Panel title="Sign behaviour">
      <div className="space-y-3">
        <Field label={`Propagation radius — ${spatial.propagation_radius_m} m`} hint="Boards within this light up">
          <input type="range" min="30" max="500" step="10" value={spatial.propagation_radius_m} onChange={e => set('propagation_radius_m', e.target.value)} className="w-full accent-brand" />
        </Field>
        <Field label={`Min confidence — ${spatial.min_confidence}%`}>
          <input type="range" min="0" max="95" step="5" value={spatial.min_confidence} onChange={e => set('min_confidence', e.target.value)} className="w-full accent-brand" />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="RED hold (s)"><Input type="number" value={spatial.red_hold_s} onChange={e => set('red_hold_s', e.target.value)} /></Field>
          <Field label="AMBER hold (s)"><Input type="number" value={spatial.amber_hold_s} onChange={e => set('amber_hold_s', e.target.value)} /></Field>
        </div>
        <div className="flex items-center gap-3">
          <Button variant={preview ? 'subtle' : 'secondary'} size="sm" onClick={() => setPreview(p => p ? null : 'arm')}>
            <Crosshair size={13} /> {preview ? 'Clear preview' : 'Preview on map'}
          </Button>
          {preview && preview !== 'arm' && <span className="text-xs text-ink-muted"><span className="text-sev-critical font-semibold">{litCount}</span> light RED</span>}
          {preview === 'arm' && <span className="text-xs text-orange">Click the map →</span>}
        </div>
      </div>
    </Panel>
  )
}

function StakeholderChecks({ items, selected, onToggle }) {
  if (items.length === 0) return <p className="text-xs text-ink-muted">Add stakeholders above first.</p>
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(s => (
        <button key={s.id} onClick={() => onToggle(s.id)}
          className={`px-2.5 py-1 rounded-full border text-xs transition-colors ${selected.includes(s.id) ? 'bg-brand/10 border-brand text-brand' : 'border-line text-ink-muted hover:bg-surface-alt'}`}>
          {s.name}
        </button>
      ))}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 5 — Review & Test
// ════════════════════════════════════════════════════════════════════════════
function StepReview({ ucId, zoneMarker, center, scenario, spatial, devices, signs, stakeholders, rules, addToast }) {
  const [liveSigns, setLiveSigns] = useState(signs)
  const [firing, setFiring] = useState(false)
  const placedDevices = devices.filter(d => d.lat != null)
  const radius = Number(spatial.propagation_radius_m) || 120
  const ruleObj = rules[0]?.conditions?.find(c => c.field === 'object_type')?.value || scenario.objectTypes[0] || 'object'
  const ruleConf = rules[0]?.conditions?.find(c => c.field === 'confidence')?.value
  const testConf = Math.min(99, (Number(ruleConf) || 60) + 15)

  useEffect(() => {
    let active = true
    const z = signs[0]?.zone_id
    if (!z) return
    const tick = async () => { try { const all = await api('GET', '/api/road-signs'); if (active) setLiveSigns(all.filter(s => s.zone_id === z)) } catch {} }
    tick(); const t = setInterval(tick, 2500)
    return () => { active = false; clearInterval(t) }
  }, [signs])

  async function fireTest() {
    if (placedDevices.length === 0) { addToast({ message: 'Place a sensor with coordinates to test.', type: 'error' }); return }
    setFiring(true)
    try {
      const res = await simulateEvent({ use_case_id: ucId, object_type: ruleObj, confidence: testConf, lat: center[0], lng: center[1] })
      addToast({ message: `Test fired via ${res.device_name}${res.incident_id ? ` · ${res.incident_id} opened` : ''}`, type: 'success' })
    } catch (e) { addToast({ message: `Test failed: ${e.message}`, type: 'error' }) }
    finally { setFiring(false) }
  }

  return (
    <StepLayout title="Review & test"
      description="Confirm everything, then fire a real test detection — boards light and an incident opens, exactly like production."
      map={<WizardMap bare center={center} zoom={15} zone={zoneMarker} devices={placedDevices} signs={liveSigns} showRings radius={radius} />}>
      <div className="space-y-2">
        <Row label="Scenario" value={scenario.name} sub={scenario.objectTypes.join(', ')} accent={scenario.color} />
        <Row label="Location" value={zoneMarker?.name} sub={scenario.location?.label} />
        <Row label="Sensors" value={`${devices.length}`} />
        <Row label="Signs" value={`${signs.length}`} />
        <Row label="Stakeholders" value={`${stakeholders.length}`} />
        <Row label="Rules" value={`${rules.length}`} />
        <Row label="Spatial" value={`${spatial.propagation_radius_m} m`} sub={`RED ${spatial.red_hold_s}s · AMBER ${spatial.amber_hold_s}s`} />
      </div>
      {rules.length === 0 && <Banner variant="warning">Create a rule in the previous step to enable testing.</Banner>}
      <Button onClick={fireTest} loading={firing} disabled={rules.length === 0} className="w-full justify-center">
        <FlaskConical size={14} /> Run test detection
      </Button>
      <p className="text-xs text-ink-muted">Fires a <span className="font-medium text-ink">{ruleObj}</span> at {testConf}% at the zone centre. Watch the boards on the map →</p>
    </StepLayout>
  )
}

function Row({ label, value, sub, accent }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 bg-white border border-line rounded-lg">
      <div className="flex items-center gap-2 text-xs font-semibold text-ink-muted uppercase tracking-wide">
        {accent && <span className="w-2 h-2 rounded-full" style={{ background: accent }} />}{label}
      </div>
      <div className="text-right min-w-0">
        <div className="text-sm font-semibold text-ink truncate">{value || '—'}</div>
        {sub && <div className="text-xs text-ink-muted truncate max-w-[200px]">{sub}</div>}
      </div>
    </div>
  )
}
