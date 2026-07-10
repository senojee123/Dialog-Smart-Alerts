import { Clock } from 'lucide-react'
import SeverityChip from '../common/SeverityChip.jsx'
import StatusBadge from '../common/StatusBadge.jsx'
import { relativeTime } from '../../lib/format.js'

function DeliveryCell({ stakeholders = [] }) {
  let total = 0, delivered = 0, failed = 0
  stakeholders.forEach(s => s.channels.forEach(c => {
    total++
    if (c.status === 'delivered') delivered++
    if (c.status === 'failed') failed++
  }))
  if (total === 0) return <span className="text-ink-muted text-xs">—</span>
  const color = failed > 0 ? 'text-sev-critical' : delivered === total ? 'text-sev-low' : 'text-ink-muted'
  return <span className={`text-xs font-medium ${color}`}>{delivered}/{total}</span>
}

function ConfidenceCell({ confidence }) {
  if (confidence == null) return <Clock size={14} className="text-ink-muted" />
  const pct = Math.round(confidence * 100)
  const color = pct >= 80 ? 'text-sev-low' : pct >= 60 ? 'text-ink' : 'text-ink-muted'
  return <span className={`text-xs font-semibold ${color}`}>{pct}%</span>
}

export default function IncidentRow({ incident, selected, onClick }) {
  const isCritical = incident.severity === 'CRITICAL'
  return (
    <tr
      onClick={onClick}
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick?.()}
      className={`cursor-pointer text-sm transition-colors outline-none
        ${selected ? 'bg-brand/5' : isCritical ? 'bg-sev-critical/5 hover:bg-sev-critical/10' : 'hover:bg-surface'}
        focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-inset`}
    >
      <td className="px-3 py-3">
        <SeverityChip severity={incident.severity} pulse={isCritical} />
      </td>
      <td className="px-3 py-3 font-mono text-xs text-ink-muted whitespace-nowrap">{incident.incident_id}</td>
      <td className="px-3 py-3 text-ink-muted whitespace-nowrap" title={`Opened: ${incident.opened_at}`}>{relativeTime(incident.updated_at || incident.opened_at)}</td>
      <td className="px-3 py-3">
        <div className="text-ink">{incident.zone}</div>
        <div className="text-xs text-ink-muted truncate max-w-[120px]">{incident.location?.description}</div>
      </td>
      <td className="px-3 py-3 capitalize">{incident.object}</td>
      <td className="px-3 py-3"><ConfidenceCell confidence={incident.confidence} /></td>
      <td className="px-3 py-3"><DeliveryCell stakeholders={incident.stakeholders} /></td>
      <td className="px-3 py-3">
        {incident.hardware?.state
          ? <StatusBadge status={incident.hardware.state} />
          : <span className="text-xs text-ink-muted">—</span>
        }
      </td>
      <td className="px-3 py-3"><StatusBadge status={incident.status} /></td>
    </tr>
  )
}
