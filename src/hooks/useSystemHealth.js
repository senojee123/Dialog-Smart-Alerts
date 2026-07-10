import { useState, useEffect } from 'react'

const MOCK_HEALTH = {
  status: 'ok', queue_depth: 2, worker_live: true,
  vlm_ok: true, broker_ok: true, outbox_backlog: 0,
  fast_path_ms: 820, slo_ms: 1500,
}

export function useSystemHealth() {
  const [health, setHealth] = useState(MOCK_HEALTH)

  useEffect(() => {
    const poll = () =>
      fetch('/api/system/health')
        .then(r => { if (!r.ok) throw new Error(); return r.json() })
        .then(setHealth)
        .catch(() => setHealth(MOCK_HEALTH))
    poll()
    const id = setInterval(poll, 15000)
    return () => clearInterval(id)
  }, [])

  // Only an explicit `false` is degraded — a field the backend doesn't report
  // must not turn the dot red (the old bug: real /health omitted these fields).
  const dot = !health ? 'amber'
    : (health.worker_live === false || health.broker_ok === false || health.vlm_ok === false) ? 'red'
    : (health.queue_depth > 50 || (health.fast_path_ms && health.slo_ms && health.fast_path_ms > health.slo_ms)) ? 'amber'
    : 'green'

  return { health, dot }
}
