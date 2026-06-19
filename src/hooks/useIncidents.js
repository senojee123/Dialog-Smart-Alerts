import { useState, useEffect, useCallback } from 'react'
import { MOCK_INCIDENTS } from '../mock/incidents.js'

export function useIncidents() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)

  useEffect(() => {
    fetch('/api/incidents')
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json() })
      .then(data => { setIncidents(data); setLoading(false) })
      .catch(() => {
        // Backend not running — fall back to mock data silently
        setIncidents(MOCK_INCIDENTS)
        setLoading(false)
      })
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

  const updateIncident = useCallback(async (id, patch) => {
    // Optimistic local update first…
    setIncidents(prev => prev.map(i => i.incident_id === id ? { ...i, ...patch } : i))
    // …then persist to the backend (id === incident_id) and adopt its response.
    try {
      const res = await fetch(`/api/incidents/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (res.ok) {
        const updated = await res.json()
        setIncidents(prev => prev.map(i => i.incident_id === id ? updated : i))
      }
    } catch {
      // Backend unavailable — keep the optimistic update
    }
  }, [])

  return { incidents, loading, error, applyEvent, updateIncident }
}
