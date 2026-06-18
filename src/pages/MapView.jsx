import { useState } from 'react'
import MapPanel from '../components/map/MapPanel.jsx'
import IncidentDetail from '../components/incidents/IncidentDetail.jsx'
import { useIncidents } from '../hooks/useIncidents.js'

export default function MapView() {
  const { incidents } = useIncidents()
  const [selected, setSelected] = useState(null)

  const selectedIncident = incidents.find(i => i.incident_id === selected?.incident_id) ?? null

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1">
        <MapPanel
          incidents={incidents}
          selectedId={selectedIncident?.incident_id}
          onSelectIncident={setSelected}
        />
      </div>
      {selectedIncident && (
        <IncidentDetail
          incident={selectedIncident}
          onClose={() => setSelected(null)}
          onCloseIncident={() => setSelected(null)}
        />
      )}
    </div>
  )
}
