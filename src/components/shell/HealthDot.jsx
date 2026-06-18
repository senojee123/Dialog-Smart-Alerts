import { useState } from 'react'
import { Activity, X } from 'lucide-react'
import { useSystemHealth } from '../../hooks/useSystemHealth.js'

const DOT_COLOR = { green: 'bg-sev-low', amber: 'bg-sev-medium', red: 'bg-sev-critical' }

export default function HealthDot() {
  const { health, dot } = useSystemHealth()
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 text-white/80 hover:text-white text-sm"
        title="System health"
      >
        <span className={`w-2.5 h-2.5 rounded-full ${DOT_COLOR[dot]} ${dot !== 'green' ? 'animate-pulse-sev' : ''}`} />
        <Activity size={14} />
      </button>

      {open && health && (
        <div className="fixed inset-0 z-50 flex items-start justify-end pt-14 pr-4" onClick={() => setOpen(false)}>
          <div
            className="bg-white rounded-lg shadow-lg border border-line p-5 w-80"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-4">
              <span className="font-semibold text-ink">System Health</span>
              <button onClick={() => setOpen(false)}><X size={16} className="text-ink-muted" /></button>
            </div>
            <div className="space-y-2 text-sm">
              <Row label="Worker" ok={health.worker_live} />
              <Row label="VLM / AI Provider" ok={health.vlm_ok} />
              <Row label="Message Broker" ok={health.broker_ok} />
              <Row label="Queue depth" text={String(health.queue_depth)} ok={health.queue_depth < 50} />
              <Row label="Outbox backlog" text={String(health.outbox_backlog)} ok={health.outbox_backlog < 10} />
              <Row
                label="Fast-path latency"
                text={`${health.fast_path_ms}ms (SLO ≤${health.slo_ms}ms)`}
                ok={health.fast_path_ms <= health.slo_ms}
              />
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Row({ label, ok, text }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-ink-muted">{label}</span>
      <span className={`font-medium ${ok ? 'text-sev-low' : 'text-sev-critical'}`}>
        {text ?? (ok ? 'OK' : 'DEGRADED')}
      </span>
    </div>
  )
}
