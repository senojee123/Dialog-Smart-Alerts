// In dev the Vite proxy buffers SSE frames (connection opens but events
// never arrive). Connect the EventSource directly to the backend so frames
// are streamed in real time. CORS is open on the backend (allow_origins=["*"]).
// In production the SPA is served by the backend itself so a relative path works.
const API_BASE  = import.meta.env.VITE_API_BASE ?? '/api'
const STREAM_BASE = import.meta.env.DEV
  ? 'http://localhost:8000/api'
  : API_BASE

// Backend SSE frames are { type, data } envelopes. We forward only the
// incident-related ones to the incidents handler.
const INCIDENT_TYPES = new Set(['incident_new', 'incident_updated'])

export function createIncidentStream({ onEvent, onStatusChange }) {
  let es

  function connect() {
    es = new EventSource(`${STREAM_BASE}/stream`)

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
