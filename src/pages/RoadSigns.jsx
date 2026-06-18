import { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Circle, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { AlertTriangle, CheckCircle, WifiOff, Map, Crosshair } from 'lucide-react'
import RoadSignCard, { SIGN_STATE } from '../components/roadsigns/RoadSignCard.jsx'
import { useApi } from '../hooks/useApi.js'
import { useIncidents } from '../hooks/useIncidents.js'
import { relativeTime } from '../lib/format.js'

// ── helpers ──────────────────────────────────────────────────────────────────

function haversineM(lat1, lng1, lat2, lng2) {
  const R = 6371000
  const toRad = d => (d * Math.PI) / 180
  const dPhi = toRad(lat2 - lat1)
  const dLmb = toRad(lng2 - lng1)
  const a = Math.sin(dPhi / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLmb / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function signIcon(state) {
  const color = state === 'WARNING' ? '#D92D20'
    : state === 'CAUTION' ? '#F2841C'
    : state === 'OFFLINE' ? '#667085' : '#12B76A'
  const pulse = state === 'WARNING'
  return L.divIcon({
    html: `<div style="background:${color};width:14px;height:14px;border-radius:3px;border:2px solid white;
            box-shadow:0 1px 4px rgba(0,0,0,.5)${pulse ? ',0 0 0 6px ' + color + '55' : ''};
            transform:rotate(45deg)"></div>`,
    className: '', iconSize: [18, 18], iconAnchor: [9, 9],
  })
}

const SUMMARY_ITEMS = [
  { state: 'WARNING', label: 'Warning', Icon: AlertTriangle, color: 'text-sev-critical' },
  { state: 'CAUTION', label: 'Caution', Icon: AlertTriangle, color: 'text-orange' },
  { state: 'CLEAR',   label: 'Clear',   Icon: CheckCircle,   color: 'text-sev-low' },
  { state: 'OFFLINE', label: 'Offline', Icon: WifiOff,       color: 'text-ink-muted' },
]

function MapClickHandler({ active, onPick }) {
  useMapEvents({ click(e) { if (active) onPick(e.latlng) } })
  return null
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function RoadSigns() {
  const { data: signs, fetchAll } = useApi('/api/road-signs')
  const { data: zones }   = useApi('/api/zones')
  const { data: devices } = useApi('/api/devices')
  const { incidents } = useIncidents()

  const [selected, setSelected]   = useState(null)
  const [viewMode, setViewMode]   = useState('grid')
  const [filterState, setFilter]  = useState('ALL')
  const [simulating, setSimulating] = useState(false)
  const [toast, setToast]         = useState(null)

  // Live polling — picks up the spatial decay (RED→AMBER→GREEN) over time.
  useEffect(() => {
    const t = setInterval(fetchAll, 4000)
    return () => clearInterval(t)
  }, [fetchAll])

  const zoneName = useMemo(() => {
    const m = {}; zones.forEach(z => { m[z.id] = z.name }); return m
  }, [zones])

  const activeIncidents = useMemo(
    () => incidents.filter(i => i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW'),
    [incidents]
  )

  const enriched = useMemo(() => signs.map(sign => ({
    sign: { ...sign, zone: zoneName[sign.zone_id] || sign.zone_id, last_updated: sign.updated_at },
    state: sign.state || 'CLEAR',
    nearby: activeIncidents.find(i => i.zone_id === sign.zone_id) ?? null,
  })), [signs, zoneName, activeIncidents])

  const counts = useMemo(() => {
    const c = { WARNING: 0, CAUTION: 0, CLEAR: 0, OFFLINE: 0 }
    enriched.forEach(e => { if (c[e.state] !== undefined) c[e.state]++ })
    return c
  }, [enriched])

  const filtered = filterState === 'ALL' ? enriched : enriched.filter(e => e.state === filterState)
  const selectedEntry = enriched.find(e => e.sign.id === selected) ?? null

  async function simulateAt(latlng) {
    setSimulating(false)
    // Find the nearest device to the clicked point
    const withCoords = devices.filter(d => d.lat != null && d.lng != null)
    if (withCoords.length === 0) { setToast('No devices with coordinates to attribute the detection.'); return }
    let nearest = withCoords[0], best = Infinity
    for (const d of withCoords) {
      const dist = haversineM(latlng.lat, latlng.lng, d.lat, d.lng)
      if (dist < best) { best = dist; nearest = d }
    }
    try {
      const res = await fetch('/api/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: nearest.id, object_type: 'elephant', confidence: 90,
          lat: latlng.lat, lng: latlng.lng,
        }),
      })
      const data = await res.json()
      setToast(`Detection sent via ${nearest.name}${data.incident_id ? ` · ${data.incident_id}` : ''}`)
      setTimeout(fetchAll, 400)
      setTimeout(() => setToast(null), 4000)
    } catch (e) {
      setToast(`Failed: ${e.message}`)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-line bg-surface shrink-0">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-xl font-semibold text-ink">Road Sign Boards</h1>
            <p className="text-sm text-ink-muted mt-0.5">
              {signs.length} LED boards · states light by proximity to live detections
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {SUMMARY_ITEMS.map(({ state, label, Icon, color }) => (
              <button
                key={state}
                onClick={() => setFilter(f => f === state ? 'ALL' : state)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm border transition-colors
                  ${filterState === state ? 'bg-ink text-white border-ink' : `border-line ${color} hover:bg-surface-alt`}`}
              >
                <Icon size={13} />
                <span className="font-semibold">{counts[state]}</span>
                <span className="text-xs">{label}</span>
              </button>
            ))}

            <div className="flex border border-line rounded-lg overflow-hidden">
              <button onClick={() => setViewMode('grid')}
                className={`px-3 py-1.5 text-sm ${viewMode === 'grid' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}>
                Grid
              </button>
              <button onClick={() => setViewMode('map')}
                className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${viewMode === 'map' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}>
                <Map size={14} /> Map
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-auto relative">
          {viewMode === 'grid' ? (
            <div className="p-6 grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {filtered.map(({ sign, state, nearby }) => (
                <RoadSignCard key={sign.id} sign={sign} derivedState={state}
                  nearbyIncident={nearby} selected={selected === sign.id}
                  onSelect={() => setSelected(id => id === sign.id ? null : sign.id)} />
              ))}
              {filtered.length === 0 && (
                <div className="col-span-4 py-16 text-center text-ink-muted text-sm">No boards match this filter.</div>
              )}
            </div>
          ) : (
            <>
              {/* Simulate control */}
              <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] flex flex-col items-center gap-2">
                <button
                  onClick={() => setSimulating(s => !s)}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-medium shadow-lg transition-colors
                    ${simulating ? 'bg-orange text-white' : 'bg-white text-ink border border-line hover:bg-surface-alt'}`}
                >
                  <Crosshair size={14} />
                  {simulating ? 'Click the map to drop a detection…' : 'Simulate detection'}
                </button>
                {toast && (
                  <div className="bg-ink text-white text-xs px-3 py-1.5 rounded-full shadow">{toast}</div>
                )}
              </div>

              <MapContainer center={[6.3818, 81.48]} zoom={15} style={{ height: '100%', width: '100%' }}
                            className={simulating ? 'cursor-crosshair' : ''}>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <MapClickHandler active={simulating} onPick={simulateAt} />

                {/* Device positions (cameras/sensors) */}
                {devices.filter(d => d.lat && d.lng).map(d => (
                  <Circle key={d.id} center={[d.lat, d.lng]} radius={12}
                          pathOptions={{ color: '#1570EF', fillColor: '#1570EF', fillOpacity: 0.6, weight: 1 }}>
                    <Popup><div className="text-xs"><b>{d.name}</b><br />{d.type}</div></Popup>
                  </Circle>
                ))}

                {/* Sign boards */}
                {enriched.map(({ sign, state, nearby }) => (
                  <Marker key={sign.id} position={[sign.lat, sign.lng]} icon={signIcon(state)}>
                    <Popup>
                      <div className="text-xs min-w-[160px] leading-snug">
                        <div className="font-semibold">{sign.name}</div>
                        <div className="text-ink-muted">{sign.road} · km {sign.km_marker}</div>
                        <div className="mt-1 font-medium" style={{ color: SIGN_STATE[state]?.color }}>{state}</div>
                        {nearby && <div className="mt-1 text-sev-critical">{nearby.incident_id || nearby.id}</div>}
                      </div>
                    </Popup>
                  </Marker>
                ))}
              </MapContainer>
            </>
          )}
        </div>

        {/* Detail panel */}
        {selectedEntry && (
          <aside className="w-72 shrink-0 border-l border-line bg-white overflow-y-auto">
            <div className="p-4 border-b border-line">
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-semibold text-ink">{selectedEntry.sign.name}</div>
                  <div className="text-xs text-ink-muted mt-0.5">{selectedEntry.sign.id}</div>
                </div>
                <button onClick={() => setSelected(null)} className="text-ink-muted hover:text-ink text-lg leading-none">×</button>
              </div>
            </div>

            <div className="p-4 space-y-4 text-sm">
              <div>
                <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Current State</div>
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded font-bold text-xs tracking-widest"
                  style={{ background: SIGN_STATE[selectedEntry.state]?.color + '20', color: SIGN_STATE[selectedEntry.state]?.color }}>
                  {selectedEntry.state}
                </div>
              </div>

              <div>
                <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Location</div>
                <dl className="space-y-1">
                  <Row label="Road"    value={selectedEntry.sign.road} />
                  <Row label="Marker"  value={`km ${selectedEntry.sign.km_marker}`} />
                  <Row label="Zone"    value={selectedEntry.sign.zone} />
                  <Row label="Online"  value={selectedEntry.sign.online ? 'Yes' : 'No'} />
                  <Row label="Updated" value={relativeTime(selectedEntry.sign.last_updated)} />
                </dl>
              </div>

              {selectedEntry.nearby ? (
                <div>
                  <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Triggering Incident</div>
                  <div className="p-3 bg-sev-critical/5 border border-sev-critical/20 rounded-lg space-y-1">
                    <div className="font-mono text-xs text-sev-critical font-semibold">{selectedEntry.nearby.incident_id || selectedEntry.nearby.id}</div>
                    <div className="text-xs text-ink capitalize">{selectedEntry.nearby.object} · {selectedEntry.nearby.severity}</div>
                    <div className="text-xs text-ink-muted">{selectedEntry.sign.zone}</div>
                  </div>
                </div>
              ) : (
                <div>
                  <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Triggering Incident</div>
                  <p className="text-xs text-ink-muted">No active incidents near this board.</p>
                </div>
              )}

              <div className="p-3 bg-surface rounded-lg text-xs text-ink-muted leading-relaxed">
                <strong className="text-ink">Proximity logic:</strong> Boards light by distance to live detections.
                A detection within range shows <span className="text-sev-critical font-medium">RED</span> for ~90s,
                fades to <span className="text-orange font-medium">AMBER</span>, then
                <span className="text-sev-low font-medium"> GREEN</span> once clear.
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between">
      <span className="text-ink-muted">{label}</span>
      <span className="text-ink font-medium">{value}</span>
    </div>
  )
}
