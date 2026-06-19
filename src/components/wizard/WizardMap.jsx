import { MapContainer, TileLayer, Marker, Popup, Circle, useMapEvents } from 'react-leaflet'
import L from 'leaflet'

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

function ClickHandler({ active, onPlace }) {
  useMapEvents({ click(e) { if (active) onPlace?.(e.latlng) } })
  return null
}

// ── component ─────────────────────────────────────────────────────────────────

export default function WizardMap({
  center = [6.3818, 81.48],
  zoom = 14,
  height = 380,
  devices = [],
  signs = [],
  placing = false,
  onPlace,
  preview = null,        // { lat, lng, radius }
}) {
  return (
    <div className="rounded-lg overflow-hidden border border-line" style={{ height }}>
      <MapContainer center={center} zoom={zoom} style={{ height: '100%', width: '100%' }}
                    className={placing ? 'cursor-crosshair' : ''}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler active={placing} onPlace={onPlace} />

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
    </div>
  )
}
