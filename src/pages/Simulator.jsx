import { useEffect, useMemo, useRef, useState } from 'react'
import { PlayCircle, Crosshair, Play, Square, RotateCcw, Trash2, MapPin, FlaskConical } from 'lucide-react'
import {
  PageHeader, Card, Panel, Field, Input, Select, SegmentedControl,
  Button, Banner, Badge, ConfirmDialog, ToastStack,
} from '../components/ui'
import SimMap from '../components/sim/SimMap.jsx'
import { useApi } from '../hooks/useApi.js'
import { useToast } from '../hooks/useToast.js'
import { simulateEvent, startScenario, stopScenario, listScenarios, resetSimulation, deriveTestDefaults } from '../lib/sim.js'

const DEFAULT_CENTER = [6.3818, 81.48]

export default function Simulator() {
  const { data: useCases } = useApi('/api/use-cases')
  const { data: rules }    = useApi('/api/rules')
  const { data: devices }  = useApi('/api/devices')
  const { data: zones }    = useApi('/api/zones')
  const { data: signs, fetchAll: refetchSigns } = useApi('/api/road-signs')
  const { toasts, addToast, removeToast } = useToast()

  const [ucId, setUcId]     = useState('')
  const [object, setObject] = useState('object')
  const [conf, setConf]     = useState(85)
  const [mode, setMode]     = useState('single')   // single | path
  const [path, setPath]     = useState([])
  const [steps, setSteps]   = useState(14)
  const [speed, setSpeed]   = useState(2)          // seconds between detections
  const [run, setRun]       = useState(null)       // active scenario meta
  const [confirmReset, setConfirmReset] = useState(false)
  const runningRef = useRef(false)

  // Pick the first use case once loaded.
  useEffect(() => {
    if (!ucId && useCases.length) setUcId(useCases.find(u => u.active)?.id || useCases[0].id)
  }, [useCases, ucId])

  // When the use case (or its rules) change, derive object/confidence defaults.
  useEffect(() => {
    if (!ucId) return
    const d = deriveTestDefaults(rules, ucId)
    setObject(d.object_type); setConf(d.confidence)
  }, [ucId, rules])

  // Poll sign states so the map reflects the RED→AMBER→GREEN decay live.
  useEffect(() => {
    const t = setInterval(refetchSigns, 2500)
    return () => clearInterval(t)
  }, [refetchSigns])

  // ── scoped collections ──────────────────────────────────────────────────────
  const ucZoneIds = useMemo(() => new Set(zones.filter(z => z.use_case_id === ucId).map(z => z.id)), [zones, ucId])
  const ucDevices = useMemo(() => devices.filter(d => d.use_case_id === ucId && d.lat != null), [devices, ucId])
  const ucSigns   = useMemo(() => signs.filter(s => ucZoneIds.has(s.zone_id) && s.lat != null), [signs, ucZoneIds])
  const spatial   = useCases.find(u => u.id === ucId)?.spatial
  const radius    = Number(spatial?.propagation_radius_m) || 120

  const center = ucDevices[0] ? [ucDevices[0].lat, ucDevices[0].lng]
    : ucSigns[0] ? [ucSigns[0].lat, ucSigns[0].lng] : DEFAULT_CENTER

  const hasSensors = ucDevices.length > 0
  const litCount = ucSigns.filter(s => s.state === 'WARNING' || s.state === 'CAUTION').length

  // ── poll active scenario position ───────────────────────────────────────────
  useEffect(() => {
    if (!run) return
    runningRef.current = true
    const t = setInterval(async () => {
      try {
        const all = await listScenarios()
        const me = all.find(r => r.id === run.id)
        if (me) {
          setRun(me)
          if (me.status !== 'running') { runningRef.current = false; clearInterval(t); setTimeout(() => setRun(null), 1500) }
        }
      } catch { /* ignore */ }
      refetchSigns()
    }, 1200)
    return () => clearInterval(t)
  }, [run?.id, refetchSigns])

  // ── actions ─────────────────────────────────────────────────────────────────
  async function handleMapClick(latlng) {
    if (mode === 'path') {
      setPath(p => [...p, [+latlng.lat.toFixed(6), +latlng.lng.toFixed(6)]])
      return
    }
    try {
      const res = await simulateEvent({ use_case_id: ucId, object_type: object, confidence: Number(conf), lat: latlng.lat, lng: latlng.lng })
      addToast({ message: `Detection via ${res.device_name}${res.incident_id ? ` · ${res.incident_id}` : ''}`, type: 'success' })
      setTimeout(refetchSigns, 400)
    } catch (e) {
      addToast({ message: `Failed: ${e.message}`, type: 'error' })
    }
  }

  async function play() {
    if (path.length < 1) { addToast({ message: 'Add at least one path point (click the map in Path mode).', type: 'error' }); return }
    try {
      const meta = await startScenario({
        use_case_id: ucId, object_type: object, confidence: Number(conf),
        path, steps: Number(steps), step_seconds: Number(speed),
      })
      setRun(meta)
      addToast({ message: `Scenario ${meta.id} running — ${steps} detections`, type: 'info' })
    } catch (e) {
      addToast({ message: `Failed: ${e.message}`, type: 'error' })
    }
  }

  async function stop() {
    if (run) { try { await stopScenario(run.id) } catch {} ; setRun(null) }
  }

  async function doReset() {
    setConfirmReset(false)
    try {
      const r = await resetSimulation()
      addToast({ message: `Cleared ${r.events_removed} events · ${r.incidents_removed} incidents`, type: 'success' })
      setPath([]); setRun(null); setTimeout(refetchSigns, 300)
    } catch (e) {
      addToast({ message: `Reset failed: ${e.message}`, type: 'error' })
    }
  }

  const running = run?.status === 'running'

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader icon={PlayCircle} title="Simulator"
        description="Exercise the live pipeline without hardware. Detections run through the same engine as real devices."
        action={<Button variant="secondary" onClick={() => setConfirmReset(true)}><RotateCcw size={14} /> Reset sim data</Button>}
      />

      <div className="px-6 pt-3 shrink-0">
        <Banner variant="warning" title="Simulation mode">
          Everything here is tagged as simulation and can be wiped with “Reset sim data”. Real device/upload data is never touched.
        </Banner>
      </div>

      <div className="flex-1 flex gap-4 p-6 pt-3 overflow-hidden">
        {/* Controls */}
        <div className="w-80 shrink-0 overflow-y-auto space-y-4">
          <Card className="space-y-4">
            <Field label="Use case">
              <Select value={ucId} onChange={e => setUcId(e.target.value)}>
                {useCases.map(u => <option key={u.id} value={u.id}>{u.name}{u.active ? '' : ' (inactive)'}</option>)}
              </Select>
            </Field>
            {!hasSensors && (
              <Banner variant="error">This use case has no placed sensors — add devices with coordinates first.</Banner>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Object type" hint="Matches the rule"><Input value={object} onChange={e => setObject(e.target.value)} /></Field>
              <Field label={`Confidence — ${conf}%`}>
                <input type="range" min="0" max="100" step="1" value={conf}
                       onChange={e => setConf(Number(e.target.value))} className="w-full accent-brand mt-2.5" />
              </Field>
            </div>
          </Card>

          <Card padded={false}>
            <div className="px-4 pt-4">
              <SegmentedControl className="w-full"
                options={[{ value: 'single', label: 'Single detection' }, { value: 'path', label: 'Moving target' }]}
                value={mode} onChange={setMode} />
            </div>
            <div className="p-4 space-y-3">
              {mode === 'single' ? (
                <p className="text-sm text-ink-muted flex items-start gap-2">
                  <Crosshair size={15} className="text-brand mt-0.5 shrink-0" />
                  Click the map to drop one detection at that point.
                </p>
              ) : (
                <>
                  <p className="text-sm text-ink-muted flex items-start gap-2">
                    <MapPin size={15} className="text-maroon mt-0.5 shrink-0" />
                    Click the map to lay down a path, then play — a target steps along it over time.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label={`Detections — ${steps}`}>
                      <input type="range" min="2" max="40" value={steps} onChange={e => setSteps(Number(e.target.value))} className="w-full accent-brand mt-2.5" />
                    </Field>
                    <Field label={`Every ${speed}s`}>
                      <input type="range" min="1" max="6" step="0.5" value={speed} onChange={e => setSpeed(Number(e.target.value))} className="w-full accent-brand mt-2.5" />
                    </Field>
                  </div>
                  <div className="flex items-center gap-2">
                    {!running
                      ? <Button onClick={play} disabled={!hasSensors || path.length < 1}><Play size={14} /> Play scenario</Button>
                      : <Button variant="danger" onClick={stop}><Square size={14} /> Stop</Button>}
                    <Button variant="ghost" size="sm" onClick={() => setPath([])} disabled={path.length === 0 || running}>
                      <Trash2 size={13} /> Clear path
                    </Button>
                  </div>
                  {run && (
                    <div className="text-xs text-ink-muted flex items-center gap-2">
                      <Badge color={running ? 'amber' : 'green'}>{run.status}</Badge>
                      {run.emitted}/{run.steps} detections emitted
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>

          <Panel title="Live board states">
            <div className="flex items-center justify-between text-sm">
              <span className="text-ink-muted">{ucSigns.length} boards in zone</span>
              <span className="font-semibold text-sev-critical">{litCount} lit</span>
            </div>
          </Panel>
        </div>

        {/* Map */}
        <Card padded={false} className="flex-1 overflow-hidden">
          <SimMap
            center={center} devices={ucDevices} signs={ucSigns} radius={radius}
            path={path} target={running ? run?.position : null}
            active={hasSensors && (mode === 'single' || mode === 'path') && !running}
            onClick={handleMapClick}
          />
        </Card>
      </div>

      <ConfirmDialog open={confirmReset} danger title="Reset simulation data?"
        message="Removes all simulated detections, incidents and notifications. Live data is untouched."
        confirmLabel="Reset" onConfirm={doReset} onCancel={() => setConfirmReset(false)} />
      <ToastStack toasts={toasts} onRemove={removeToast} />
    </div>
  )
}
