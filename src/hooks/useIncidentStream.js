import { useEffect, useState } from 'react'
import { createIncidentStream } from '../api/stream.js'

export function useIncidentStream(applyEvent) {
  const [streamStatus, setStreamStatus] = useState('connecting')

  useEffect(() => {
    const close = createIncidentStream({
      onEvent: applyEvent,
      onStatusChange: setStreamStatus,
    })
    return close
  }, [applyEvent])

  return streamStatus
}
