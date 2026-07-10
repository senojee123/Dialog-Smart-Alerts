import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMapEvents } from 'react-leaflet'
import L from 'leaflet'

const SIGN_COLOR = { WARNING: '#D92D20', CAUTION: '#F2841C', CLEAR: '#12B76A', OFFLINE: '#667085' }

function deviceIcon() {
  return L.divIcon({
    html: `<div style="width:13px;height:13px;background:#1570EF;border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
    className: '', iconSize: [13, 13], iconAnchor: [7, 7],
  })
}

function signIcon(state) {
  const color = SIGN_COLOR[state] || '#98A2B3'
  const pulse = state === 'WARNING'
  return L.divIcon({
    html: `<div style="background:${color};width:14px;height:14px;border-radius:3px;border:2px solid white;
            box-shadow:0 1px 4px rgba(0,0,0,.5)${pulse ? ',0 0 0 6px ' + color + '55' : ''};transform:rotate(45deg)"></div>`,
    className: '', iconSize: [18, 18], iconAnchor: [9, 9],
  })
}

function targetIcon() {
  return L.divIcon({
    html: `<div style="width:16px;height:16px;background:#D92D20;border-radius:50%;border:3px solid white;box-shadow:0 0 0 5px rgba(217,45,32,.3)"></div>`,
    className: '', iconSize: [16, 16], iconAnchor: [8, 8],
  })
}

function pointIcon(n) {
  return L.divIcon({
    html: `<div style="width:18px;height:18px;background:#7B1E28;color:#fff;font-size:10px;font-weight:700;border-radius:50%;
            display:flex;align-items:center;justify-content:center;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5)">${n}</div>`,
    className: '', iconSize: [18, 18], iconAnchor: [9, 9],
  })
}

function ClickHandler({ active, onClick }) {
  useMapEvents({ click(e) { if (active) onClick?.(e.latlng) } })
  return null
}

/**
 * SimMap — shared simulation map: devices, signs (live state colours), an
 * optional path with numbered points, the live moving target, and a click
 * handler for placing detections / path points.
 */
export default function SimMap({
  center, zoom = 15, height = '100%',
  devices = [], signs = [], radius = 120,
  path = [], target = null,
  active = false, onClick, className = '',
}) {
  return (
    <div className={`rounded-lg overflow-hidden border border-line ${className}`} style={{ height }}>
      <MapContainer center={center} zoom={zoom} style={{ height: '100%', width: '100%' }}
                    className={active ? 'cursor-crosshair' : ''}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler active={active} onClick={onClick} />

        {devices.filter(d => d.lat != null && d.lng != null).map(d => (
          <Circle key={d.id} center={[d.lat, d.lng]} radius={radius}
                  pathOptions={{ color: '#1570EF', weight: 1, opacity: 0.25, fillColor: '#1570EF', fillOpacity: 0.04 }} />
        ))}
        {devices.filter(d => d.lat != null && d.lng != null).map(d => (
          <Marker key={`m-${d.id}`} position={[d.lat, d.lng]} icon={deviceIcon()}>
            <Popup><div className="text-xs"><b>{d.name}</b><br />{d.type || 'device'}</div></Popup>
          </Marker>
        ))}

        {signs.filter(s => s.lat != null && s.lng != null).map(s => (
          <Marker key={s.id} position={[s.lat, s.lng]} icon={signIcon(s.state)}>
            <Popup><div className="text-xs"><b>{s.name}</b><br />{s.state || 'CLEAR'}</div></Popup>
          </Marker>
        ))}

        {path.length > 1 && (
          <Polyline positions={path} pathOptions={{ color: '#7B1E28', weight: 3, opacity: 0.7, dashArray: '6 6' }} />
        )}
        {path.map((p, i) => (
          <Marker key={`p-${i}`} position={p} icon={pointIcon(i + 1)} />
        ))}

        {target && (
          <>
            <Circle center={[target.lat, target.lng]} radius={radius}
                    pathOptions={{ color: '#D92D20', weight: 1.5, fillColor: '#D92D20', fillOpacity: 0.1 }} />
            <Marker position={[target.lat, target.lng]} icon={targetIcon()} />
          </>
        )}
      </MapContainer>
    </div>
  )
}
