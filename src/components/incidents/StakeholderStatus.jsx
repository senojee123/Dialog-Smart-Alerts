import { CheckCircle, Clock, XCircle } from 'lucide-react'

const CHANNEL_COLOR = { delivered: 'text-sev-low', dispatched: 'text-ink-muted', failed: 'text-sev-critical' }
const ACK_LABEL     = { RECEIVED: '✓ Received', RESPONDING: '⚡ Responding' }

export default function StakeholderStatus({ stakeholders = [] }) {
  if (!stakeholders.length) return <p className="text-sm text-ink-muted">No stakeholders notified.</p>

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-ink-muted uppercase tracking-wide">
          <th className="text-left pb-2">Name / Role</th>
          <th className="text-left pb-2">Channels</th>
          <th className="text-left pb-2">Ack</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {stakeholders.map(s => (
          <tr key={s.id} className="py-2">
            <td className="py-2 pr-4">
              <div className="font-medium text-ink">{s.name}</div>
              <div className="text-xs text-ink-muted">{s.role}</div>
            </td>
            <td className="py-2 pr-4">
              <div className="flex flex-wrap gap-1.5">
                {s.channels.map((ch, i) => (
                  <span key={i} className={`flex items-center gap-1 text-xs ${CHANNEL_COLOR[ch.status] ?? 'text-ink-muted'}`}>
                    {ch.status === 'delivered'  && <CheckCircle size={12} />}
                    {ch.status === 'dispatched' && <Clock size={12} />}
                    {ch.status === 'failed'     && <XCircle size={12} />}
                    {ch.type}
                  </span>
                ))}
              </div>
            </td>
            <td className="py-2">
              {s.channels.map((ch, i) => ch.ack ? (
                <span key={i} className="text-xs text-sev-low font-medium">{ACK_LABEL[ch.ack] ?? ch.ack}</span>
              ) : null)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
