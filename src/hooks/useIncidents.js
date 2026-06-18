import { useState, useEffect, useCallback } from 'react'
import { MOCK_INCIDENTS } from '../mock/incidents.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export function useIncidents() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)

  useEffect(() => {
    if (USE_MOCK) {
      setTimeout(() => { setIncidents(MOCK_INCIDENTS); setLoading(false) }, 300)
      return
    }
    fetch('/api/incidents')
      .then(r => r.json())
      .then(data => { setIncidents(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  const applyEvent = useCallback((event) => {
    setIncidents(prev => {
      const idx = prev.findIndex(i => i.incident_id === event.incident_id)
      if (idx === -1) return [event, ...prev]
      const updated = [...prev]
      if (new Date(event.updated_at) >= new Date(prev[idx].updated_at)) {
        updated[idx] = { ...prev[idx], ...event }
      }
      return updated
    })
  }, [])

  const updateIncident = useCallback((id, patch) => {
    setIncidents(prev => prev.map(i => i.incident_id === id ? { ...i, ...patch } : i))
  }, [])

  return { incidents, loading, error, applyEvent, updateIncident }
}
