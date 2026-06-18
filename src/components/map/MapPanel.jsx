import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import { SEV_META } from '../../lib/severity.js'

function severityIcon(severity) {
  const meta = SEV_META[severity] ?? SEV_META.LOW
  return L.divIcon({
    html: `<div style="background:${meta.bg};width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>`,
    className: '',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  })
}

function AutoPan({ incidents, selectedId }) {
  const map = useMap()
  const prevSelected = useRef(null)

  useEffect(() => {
    if (!selectedId || selectedId === prevSelected.current) return
    const inc = incidents.find(i => i.incident_id === selectedId)
    if (inc?.location) {
      map.setView([inc.location.lat, inc.location.lng], Math.max(map.getZoom(), 13), { animate: true })
    }
    prevSelected.current = selectedId
  }, [selectedId, incidents, map])

  return null
}

export default function MapPanel({ incidents = [], selectedId, onSelectIncident }) {
  const center = [6.35, 81.42]

  return (
    <MapContainer
      center={center}
      zoom={11}
      style={{ height: '100%', width: '100%' }}
      className="z-0"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <AutoPan incidents={incidents} selectedId={selectedId} />

      {incidents.map(inc => {
        if (!inc.location) return null
        return (
          <Marker
            key={inc.incident_id}
            position={[inc.location.lat, inc.location.lng]}
            icon={severityIcon(inc.severity)}
          >
            <Popup>
              <div className="text-xs leading-snug min-w-[160px]">
                <div className="font-semibold">{inc.incident_id}</div>
                <div className="text-ink-muted">{inc.severity} · {inc.status}</div>
                <div className="mt-1">{inc.zone}</div>
                <button
                  onClick={() => onSelectIncident?.(inc)}
                  className="mt-2 text-brand underline text-xs"
                >
                  Open detail
                </button>
              </div>
            </Popup>
          </Marker>
        )
      })}
    </MapContainer>
  )
}
