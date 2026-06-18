import { useMemo, useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import { TriangleAlert, CheckCircle, WifiOff, Map, LayoutGrid } from 'lucide-react'
import RoadSignCard, { SIGN_STATE } from '../components/roadsigns/RoadSignCard.jsx'
import { useRoadSigns } from '../hooks/useRoadSigns.js'
import { useIncidents } from '../hooks/useIncidents.js'
import { relativeTime } from '../lib/format.js'

function deriveState(sign, activeIncidents) {
  if (!sign.online) return 'OFFLINE'
  const nearby = activeIncidents.filter(
    i => i.zone === sign.zone && (i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW')
  )
  if (nearby.some(i => i.severity === 'CRITICAL')) return 'WARNING'
  if (nearby.some(i => i.severity === 'HIGH' || i.severity === 'MEDIUM')) return 'CAUTION'
  return 'CLEAR'
}

function nearestIncident(sign, activeIncidents) {
  return activeIncidents.find(
    i => i.zone === sign.zone && (i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW')
  ) ?? null
}

function signIcon(state) {
  const color = state === 'WARNING' ? '#D92D20' : state === 'CAUTION' ? '#F2841C' : state === 'OFFLINE' ? '#667085' : '#12B76A'
  return L.divIcon({
    html: `<div style="background:${color};width:14px;height:14px;border-radius:3px;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5);transform:rotate(45deg)"></div>`,
    className: '',
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  })
}

const SUMMARY_ITEMS = [
  { state: 'WARNING', label: 'Warning',  Icon: TriangleAlert, color: 'text-sev-critical' },
  { state: 'CAUTION', label: 'Caution',  Icon: TriangleAlert, color: 'text-orange' },
  { state: 'CLEAR',   label: 'Clear',    Icon: CheckCircle,   color: 'text-sev-low' },
  { state: 'OFFLINE', label: 'Offline',  Icon: WifiOff,       color: 'text-ink-muted' },
]

export default function RoadSigns() {
  const { signs: ROAD_SIGNS } = useRoadSigns()
  const { incidents } = useIncidents()
  const [selected, setSelected]     = useState(null)
  const [viewMode, setViewMode]     = useState('grid')
  const [filterState, setFilter]    = useState('ALL')

  const activeIncidents = useMemo(
    () => incidents.filter(i => i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW'),
    [incidents]
  )

  const enriched = useMemo(() =>
    MOCK_ROAD_SIGNS.map(sign => ({
      sign,
      state:   deriveState(sign, activeIncidents),
      nearby:  nearestIncident(sign, activeIncidents),
    })),
    [activeIncidents]
  )

  const counts = useMemo(() => {
    const c = { WARNING: 0, CAUTION: 0, CLEAR: 0, OFFLINE: 0 }
    enriched.forEach(e => { if (c[e.state] !== undefined) c[e.state]++ })
    return c
  }, [enriched])

  const filtered = filterState === 'ALL' ? enriched : enriched.filter(e => e.state === filterState)

  const selectedEntry = enriched.find(e => e.sign.id === selected) ?? null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header bar */}
      <div className="px-6 py-4 border-b border-line bg-surface shrink-0">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-xl font-semibold text-ink">Road Sign Boards</h1>
            <p className="text-sm text-ink-muted mt-0.5">
              {MOCK_ROAD_SIGNS.length} boards · states auto-update from active incidents
            </p>
          </div>

          {/* Summary chips */}
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

            {/* View toggle */}
            <div className="flex border border-line rounded-lg overflow-hidden">
              <button
                onClick={() => setViewMode('grid')}
                className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${viewMode === 'grid' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}
              >
                <LayoutGrid size={14} /> Grid
              </button>
              <button
                onClick={() => setViewMode('map')}
                className={`px-3 py-1.5 text-sm flex items-center gap-1.5 ${viewMode === 'map' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}
              >
                <Map size={14} /> Map
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Main content */}
        <div className="flex-1 overflow-auto">
          {viewMode === 'grid' ? (
            <div className="p-6 grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {filtered.map(({ sign, state, nearby }) => (
                <RoadSignCard
                  key={sign.id}
                  sign={sign}
                  derivedState={state}
                  nearbyIncident={nearby}
                  selected={selected === sign.id}
                  onSelect={() => setSelected(id => id === sign.id ? null : sign.id)}
                />
              ))}
              {filtered.length === 0 && (
                <div className="col-span-4 py-16 text-center text-ink-muted text-sm">
                  No boards match this filter.
                </div>
              )}
            </div>
          ) : (
            <MapContainer center={[6.35, 81.42]} zoom={11} style={{ height: '100%', width: '100%' }}>
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {enriched.map(({ sign, state, nearby }) => (
                <Marker key={sign.id} position={[sign.lat, sign.lng]} icon={signIcon(state)}>
                  <Popup>
                    <div className="text-xs min-w-[160px] leading-snug">
                      <div className="font-semibold">{sign.name}</div>
                      <div className="text-ink-muted">{sign.road} · km {sign.km_marker}</div>
                      <div className="mt-1 font-medium" style={{ color: SIGN_STATE[state]?.color }}>
                        {state}
                      </div>
                      {nearby && <div className="mt-1 text-sev-critical">{nearby.incident_id}</div>}
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
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
              {/* Current state */}
              <div>
                <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Current State</div>
                <div
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded font-bold text-xs tracking-widest"
                  style={{
                    background: SIGN_STATE[selectedEntry.state]?.color + '20',
                    color: SIGN_STATE[selectedEntry.state]?.color,
                  }}
                >
                  {selectedEntry.state}
                </div>
              </div>

              {/* Location */}
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

              {/* Nearby incident */}
              {selectedEntry.nearby ? (
                <div>
                  <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Triggering Incident</div>
                  <div className="p-3 bg-sev-critical/5 border border-sev-critical/20 rounded-lg space-y-1">
                    <div className="font-mono text-xs text-sev-critical font-semibold">{selectedEntry.nearby.incident_id}</div>
                    <div className="text-xs text-ink capitalize">{selectedEntry.nearby.object} · {selectedEntry.nearby.severity}</div>
                    <div className="text-xs text-ink-muted">{selectedEntry.nearby.zone}</div>
                    <div className="text-xs text-ink-muted">{relativeTime(selectedEntry.nearby.opened_at)}</div>
                  </div>
                </div>
              ) : (
                <div>
                  <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Triggering Incident</div>
                  <p className="text-xs text-ink-muted">No active incidents in this zone.</p>
                </div>
              )}

              {/* How state is determined */}
              <div className="p-3 bg-surface rounded-lg text-xs text-ink-muted leading-relaxed">
                <strong className="text-ink">Auto-state logic:</strong> Board state is derived from active incidents in the same zone.
                CRITICAL → WARNING (red). HIGH/MEDIUM → CAUTION (amber). No active incidents → CLEAR.
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
