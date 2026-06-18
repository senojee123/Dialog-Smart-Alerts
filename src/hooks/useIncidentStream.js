import { useEffect, useState } from 'react'
import { createIncidentStream } from '../api/stream.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export function useIncidentStream(applyEvent) {
  const [streamStatus, setStreamStatus] = useState('live')

  useEffect(() => {
    if (USE_MOCK) {
      setStreamStatus('mock')
      return
    }
    const close = createIncidentStream({
      onEvent: applyEvent,
      onStatusChange: setStreamStatus,
    })
    return close
  }, [applyEvent])

  return streamStatus
}
