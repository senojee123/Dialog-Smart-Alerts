const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export function createIncidentStream({ onEvent, onStatusChange, lastEventId }) {
  let es
  let lastId = lastEventId ?? ''

  function connect() {
    const url = `${BASE}/stream/incidents${lastId ? `?lastEventId=${lastId}` : ''}`
    es = new EventSource(url)

    es.onopen = () => onStatusChange?.('live')

    es.onmessage = (e) => {
      if (e.lastEventId) lastId = e.lastEventId
      try {
        const data = JSON.parse(e.data)
        onEvent?.(data)
      } catch {
        // ignore malformed frames
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
