const BASE = import.meta.env.VITE_API_BASE ?? '/api'

// Backend SSE frames are { type, data } envelopes. We forward only the
// incident-related ones to the incidents handler.
const INCIDENT_TYPES = new Set(['incident_new', 'incident_updated'])

export function createIncidentStream({ onEvent, onStatusChange }) {
  let es

  function connect() {
    es = new EventSource(`${BASE}/stream`)

    es.onopen = () => onStatusChange?.('live')

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg && INCIDENT_TYPES.has(msg.type) && msg.data) {
          onEvent?.(msg.data)
        }
      } catch {
        // ignore malformed / non-JSON frames (heartbeats, connected ping)
      }
    }

    es.onerror = () => {
      onStatusChange?.('reconnecting')
      es.close()
      setTimeout(connect, 3000)
    }
  }

  connect()
  return () => es?.close()
}
