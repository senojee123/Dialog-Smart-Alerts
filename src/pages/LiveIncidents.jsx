import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import IncidentTable from '../components/incidents/IncidentTable.jsx'
import IncidentDetail from '../components/incidents/IncidentDetail.jsx'
import MapPanel from '../components/map/MapPanel.jsx'
import ToastStack from '../components/common/Toast.jsx'
import { useIncidents } from '../hooks/useIncidents.js'
import { useIncidentStream } from '../hooks/useIncidentStream.js'
import { useToast } from '../hooks/useToast.js'

export default function LiveIncidents() {
  const { playCriticalCue } = useOutletContext() ?? {}
  const { incidents, loading, error, applyEvent, updateIncident } = useIncidents()
  const streamStatus = useIncidentStream(applyEvent)
  const { toasts, addToast, removeToast } = useToast()
  const [selected, setSelected] = useState(null)

  function handleSelect(incident) {
    setSelected(prev => prev?.incident_id === incident.incident_id ? null : incident)
  }

  function handleCloseIncident(id) {
    updateIncident(id, { status: 'CLOSED' })
    addToast({ message: `Incident ${id} closed.`, type: 'success' })
    setSelected(null)
  }

  function handleHardwareOverride(unitId, state) {
    if (!selected) return
    updateIncident(selected.incident_id, {
      hardware: { ...selected.hardware, state },
    })
    addToast({ message: `Hardware ${unitId} set to ${state}.`, type: 'success' })
  }

  const selectedIncident = incidents.find(i => i.incident_id === selected?.incident_id) ?? null

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left: table ~55% */}
      <div className="flex flex-col overflow-hidden" style={{ flex: '0 0 55%' }}>
        {error && (
          <div className="px-4 py-2 bg-sev-critical/10 text-sev-critical text-sm border-b border-line">
            Failed to load incidents. <button onClick={() => window.location.reload()} className="underline">Retry</button>
          </div>
        )}
        <IncidentTable
          incidents={incidents}
          loading={loading}
          selectedId={selectedIncident?.incident_id}
          onSelect={handleSelect}
        />
      </div>

      {/* Right: map ~45% */}
      <div className="flex-1 overflow-hidden border-l border-line">
        <MapPanel
          incidents={incidents}
          selectedId={selectedIncident?.incident_id}
          onSelectIncident={handleSelect}
        />
      </div>

      {/* Detail drawer */}
      {selectedIncident && (
        <IncidentDetail
          incident={selectedIncident}
          onClose={() => setSelected(null)}
          onCloseIncident={handleCloseIncident}
          onHardwareOverride={handleHardwareOverride}
        />
      )}

      <ToastStack toasts={toasts} onRemove={removeToast} />
    </div>
  )
}
