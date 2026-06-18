import { useState, useEffect } from 'react'

const MOCK_HEALTH = {
  status: 'ok',
  queue_depth: 2,
  worker_live: true,
  vlm_ok: true,
  broker_ok: true,
  outbox_backlog: 0,
  fast_path_ms: 820,
  slo_ms: 1500,
}

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export function useSystemHealth() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    if (USE_MOCK) { setHealth(MOCK_HEALTH); return }
    const poll = () =>
      fetch('/api/system/health').then(r => r.json()).then(setHealth).catch(() => {})
    poll()
    const id = setInterval(poll, 15000)
    return () => clearInterval(id)
  }, [])

  const dot = !health ? 'amber'
    : (!health.worker_live || !health.broker_ok || !health.vlm_ok) ? 'red'
    : (health.queue_depth > 50 || health.fast_path_ms > health.slo_ms) ? 'amber'
    : 'green'

  return { health, dot }
}
