import { useEffect, useState } from 'react'
import IncidentTable from '../components/incidents/IncidentTable.jsx'
import IncidentDetail from '../components/incidents/IncidentDetail.jsx'

const POLL_INTERVAL_MS = 15000

async function fetchLog() {
  const r = await fetch('/api/incidents/log')
  if (!r.ok) throw new Error(r.status)
  return r.json()
}

export default function IncidentLog() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let cancelled = false
    function load() {
      fetchLog()
        .then(data => { if (!cancelled) { setIncidents(data); setLoading(false); setError(null) } })
        .catch(() => { if (!cancelled) { setError(true); setLoading(false) } })
    }
    load()
    const id = setInterval(load, POLL_INTERVAL_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  function handleSelect(incident) {
    setSelected(prev => prev?.incident_id === incident.incident_id ? null : incident)
  }

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex flex-col overflow-hidden flex-1">
        <div className="px-4 py-3 border-b border-line bg-surface shrink-0">
          <h1 className="text-sm font-semibold text-ink">Incident Log</h1>
          <p className="text-xs text-ink-muted mt-0.5">
            Incidents (active or closed) auto-archived off the dashboard after 3 hours open.
          </p>
        </div>
        {error && (
          <div className="px-4 py-2 bg-sev-critical/10 text-sev-critical text-sm border-b border-line">
            Failed to load incident log. <button onClick={() => window.location.reload()} className="underline">Retry</button>
          </div>
        )}
        <IncidentTable
          incidents={incidents}
          loading={loading}
          selectedId={selected?.incident_id}
          onSelect={handleSelect}
        />
      </div>

      {selected && (
        <IncidentDetail
          incident={selected}
          onClose={() => setSelected(null)}
          readOnly
        />
      )}
    </div>
  )
}
