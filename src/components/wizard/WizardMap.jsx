import { useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Search, Loader2 } from 'lucide-react'

// ── marker icons ──────────────────────────────────────────────────────────────
function deviceIcon() {
  return L.divIcon({
    html: `<div style="width:14px;height:14px;background:#1570EF;border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
    className: '', iconSize: [14, 14], iconAnchor: [7, 7],
  })
}
const SIGN_COLOR = { WARNING: '#D92D20', CAUTION: '#F2841C', CLEAR: '#12B76A', OFFLINE: '#667085' }
function signIcon(state) {
  const color = SIGN_COLOR[state] || '#98A2B3'
  return L.divIcon({
    html: `<div style="width:14px;height:14px;background:${color};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5);transform:rotate(45deg)"></div>`,
    className: '', iconSize: [16, 16], iconAnchor: [8, 8],
  })
}
function zoneIcon() {
  return L.divIcon({
    html: `<div style="width:16px;height:16px;background:#7B1E28;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
    className: '', iconSize: [16, 16], iconAnchor: [8, 16],
  })
}

function ClickHandler({ active, onPlace }) {
  useMapEvents({ click(e) { if (active) onPlace?.(e.latlng) } })
  return null
}

function Recenter({ center }) {
  const map = useMap()
  if (center) map.setView(center, map.getZoom(), { animate: true })
  return null
}

// ── location search (Nominatim, no API key / no dependency) ────────────────────
function SearchBox({ onPick }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [busy, setBusy] = useState(false)

  async function search(e) {
    e.preventDefault()
    if (!q.trim()) return
    setBusy(true)
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=5&q=${encodeURIComponent(q)}`)
      setResults(await res.json())
    } catch { setResults([]) } finally { setBusy(false) }
  }

  return (
    <div className="absolute top-2 left-2 z-[1000] w-72">
      <form onSubmit={search} className="flex items-center gap-1 bg-white rounded-lg shadow-popover border border-line px-2 py-1">
        <Search size={14} className="text-ink-muted shrink-0" />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search a place…"
               className="flex-1 text-sm outline-none bg-transparent text-ink placeholder:text-ink-subtle" />
        {busy && <Loader2 size={14} className="animate-spin text-ink-muted" />}
      </form>
      {results.length > 0 && (
        <ul className="mt-1 bg-white rounded-lg shadow-popover border border-line max-h-48 overflow-y-auto text-sm">
          {results.map(r => (
            <li key={r.place_id}>
              <button type="button"
                onClick={() => { onPick({ lat: +r.lat, lng: +r.lon, label: r.display_name }); setResults([]); setQ(r.display_name.split(',')[0]) }}
                className="w-full text-left px-3 py-1.5 hover:bg-surface-alt text-ink truncate">
                {r.display_name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * WizardMap — placement-oriented map used across the setup steps.
 * Shows devices (blue, with optional coverage rings), signs, the zone marker,
 * an optional test-detection preview, plus location search and click-to-place.
 */
export default function WizardMap({
  center = [6.3818, 81.48], zoom = 14, height = 340,
  devices = [], signs = [], line = [],
  zone = null, showRings = false, radius = 120,
  placing = false, onPlace, preview = null,
  searchable = false, onSearchPick, bare = false,
}) {
  const [searchCenter, setSearchCenter] = useState(null)

  return (
    <div className={bare ? 'relative h-full w-full overflow-hidden' : 'relative rounded-lg overflow-hidden border border-line'}
         style={bare ? undefined : { height }}>
      <MapContainer center={center} zoom={zoom} style={{ height: '100%', width: '100%' }}
                    className={placing ? 'cursor-crosshair' : ''}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler active={placing} onPlace={onPlace} />
        {searchCenter && <Recenter center={searchCenter} />}

        {zone && zone.lat != null && (
          <Marker position={[zone.lat, zone.lng]} icon={zoneIcon()}>
            <Popup><div className="text-xs"><b>{zone.name || 'Zone centre'}</b></div></Popup>
          </Marker>
        )}

        {showRings && devices.filter(d => d.lat != null).map(d => (
          <Circle key={`r-${d.id}`} center={[d.lat, d.lng]} radius={radius}
                  pathOptions={{ color: '#1570EF', weight: 1, opacity: 0.3, fillColor: '#1570EF', fillOpacity: 0.05 }} />
        ))}

        {devices.filter(d => d.lat != null && d.lng != null).map(d => (
          <Marker key={d.id} position={[d.lat, d.lng]} icon={deviceIcon()}>
            <Popup><div className="text-xs"><b>{d.name}</b><br />{d.type || 'device'}</div></Popup>
          </Marker>
        ))}

        {signs.filter(s => s.lat != null && s.lng != null).map(s => (
          <Marker key={s.id} position={[s.lat, s.lng]} icon={signIcon(s.state)}>
            <Popup><div className="text-xs"><b>{s.name}</b>{s.state ? <><br />{s.state}</> : null}</div></Popup>
          </Marker>
        ))}

        {line.length > 1 && (
          <Polyline positions={line} pathOptions={{ color: '#7B1E28', weight: 2, dashArray: '5 6', opacity: 0.7 }} />
        )}

        {preview && (
          <>
            <Circle center={[preview.lat, preview.lng]} radius={preview.radius}
                    pathOptions={{ color: '#D92D20', fillColor: '#D92D20', fillOpacity: 0.1, weight: 1.5 }} />
            <Marker position={[preview.lat, preview.lng]}
                    icon={L.divIcon({
                      html: `<div style="width:16px;height:16px;background:#D92D20;border-radius:50%;border:3px solid white;box-shadow:0 0 0 4px rgba(217,45,32,.3)"></div>`,
                      className: '', iconSize: [16, 16], iconAnchor: [8, 8],
                    })} />
          </>
        )}
      </MapContainer>

      {searchable && <SearchBox onPick={(p) => { setSearchCenter([p.lat, p.lng]); onSearchPick?.(p) }} />}
    </div>
  )
}
