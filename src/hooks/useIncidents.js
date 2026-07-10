import { useState, useEffect, useCallback, useRef } from 'react'
import { MOCK_INCIDENTS } from '../mock/incidents.js'

const POLL_INTERVAL_MS = 5000   // re-fetch every 5 s as a reliable fallback

async function fetchIncidents() {
  const r = await fetch('/api/incidents')
  if (!r.ok) throw new Error(r.status)
  return r.json()
}

export function useIncidents() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const usingMock = useRef(false)

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    fetchIncidents()
      .then(data => { setIncidents(data); setLoading(false) })
      .catch(() => {
        // Backend not running — fall back to mock data silently
        usingMock.current = true
        setIncidents(MOCK_INCIDENTS)
        setLoading(false)
      })
  }, [])

  // ── Polling fallback: refresh every 5 s ───────────────────────────────────
  // Guarantees the UI stays in sync even when SSE frames are missed.
  useEffect(() => {
    if (usingMock.current) return   // no backend — don't poll
    const id = setInterval(() => {
      fetchIncidents()
        .then(data => {
          setIncidents(data)
        })
        .catch(() => {})  // silently ignore transient failures
    }, POLL_INTERVAL_MS)
    return () => clearInterval(id)
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
