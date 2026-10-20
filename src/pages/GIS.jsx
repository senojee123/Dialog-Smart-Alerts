import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { resolveMediaUrl } from '../api/client'

// The GIS instance's map (services/gis), served by the backend at /gis-app/ (gis_client.py) and shown
// here in a frame. In split deployments (Vercel + Railway), resolveMediaUrl ensures the iframe points
// to the Railway backend rather than Vercel's static origin.
const GIS_APP = resolveMediaUrl('/gis-app/')

/** The frame's address: opened at a position when the link names one (`?lat=..&lng=..`). */
function frameSource(params) {
  const lat = Number(params.get('lat'))
  const lng = Number(params.get('lng'))
  if (!params.get('lat') || !params.get('lng') || !Number.isFinite(lat) || !Number.isFinite(lng)) return GIS_APP
  return `${GIS_APP}#map=16/${lat.toFixed(5)}/${lng.toFixed(5)}`
}

export default function GIS() {
  const [params] = useSearchParams()
  const src = useMemo(() => frameSource(params), [params])

  return (
    <div className="relative h-full overflow-hidden">
      {/* A new position re-opens the map there (the GIS map reads its view once, when it opens). */}
      <iframe key={src} title="GIS map" src={src} className="absolute inset-0 w-full h-full border-0" />
    </div>
  )
}
