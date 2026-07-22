import { useState } from 'react'
import { X, Image, CheckCircle, XCircle, Clock, AlertTriangle, Trash2 } from 'lucide-react'
import SeverityChip from '../common/SeverityChip.jsx'
import StatusBadge from '../common/StatusBadge.jsx'
import StakeholderStatus from './StakeholderStatus.jsx'
import Timeline from './Timeline.jsx'
import HardwareControl from './HardwareControl.jsx'
import ConfirmDialog from '../common/ConfirmDialog.jsx'
import { relativeTime, absoluteTime, formatDistance } from '../../lib/format.js'
import { resolveMediaUrl } from '../../api/client.js'

export default function IncidentDetail({ incident, onClose, onCloseIncident, onDeleteIncident, onHardwareOverride }) {
  const [confirmClose, setConfirmClose] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [notes, setNotes] = useState(incident?.operator_notes ?? '')

  if (!incident) return null

  const isOperatorReview = incident.status === 'OPERATOR_REVIEW'
  const aiIcon = incident.ai_confirmed === true
    ? <CheckCircle size={14} className="text-sev-low" />
    : incident.ai_confirmed === false
    ? <XCircle size={14} className="text-sev-critical" />
    : <Clock size={14} className="text-ink-muted" />

  return (
    <aside className="w-[480px] shrink-0 border-l border-line bg-white flex flex-col shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-line">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <SeverityChip severity={incident.severity} pulse={incident.severity === 'CRITICAL'} size="lg" />
            <StatusBadge status={incident.status} />
          </div>
          <div className="font-mono text-sm text-ink-muted">{incident.incident_id}</div>
          <div className="text-xs text-ink-muted">
            {incident.zone} · {incident.location?.description}
          </div>
          <div className="text-xs text-ink-muted">Opened {relativeTime(incident.opened_at)}</div>
        </div>
        <button onClick={onClose} className="text-ink-muted hover:text-ink mt-1">
          <X size={18} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto divide-y divide-line">

        {/* Operator review banner */}
        {isOperatorReview && (
          <div className="p-4 bg-orange/10 border-l-4 border-orange flex gap-3">
            <AlertTriangle size={16} className="text-orange shrink-0 mt-0.5" />
            <p className="text-sm text-ink">
              <strong>AI could not confirm</strong> — warning active as precaution. Operator review required.
            </p>
          </div>
        )}

        {/* Evidence */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Evidence</h4>
          {incident.incident_media
            ? <img src={resolveMediaUrl(incident.incident_media)} alt="Incident media" className="rounded-lg w-full object-cover max-h-48" />
            : (
              <div className="flex items-center gap-2 p-4 bg-surface rounded-lg text-ink-muted text-sm">
                <Image size={16} /> Media attaching…
              </div>
            )
          }
        </section>

        {/* Detection panel — confidence + generated summary (no fabricated VLM verdict) */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Detection</h4>
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              {aiIcon}
              <span className="font-medium text-ink">
                {incident.ai_confirmed === true ? 'Above alert threshold'
                  : incident.ai_confirmed === false ? 'Below alert threshold'
                  : 'Pending'}
              </span>
              {incident.confidence != null && (
                <span className="text-ink-muted ml-1">({Math.round(incident.confidence * 100)}% confidence)</span>
              )}
            </div>
            {incident.ai_summary && <p className="text-ink-muted leading-relaxed">{incident.ai_summary}</p>}
            {incident.risk_factors?.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {incident.risk_factors.map(r => (
                  <span key={r} className="px-2 py-0.5 text-xs bg-surface-alt text-ink-muted rounded">{r.replace(/_/g, ' ')}</span>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Derived facts — only what's actually computed today */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Detection Context</h4>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <Fact label="Object" value={incident.object} />
            <Fact label="Detections in zone" value={String(incident.detections_in_zone ?? '—')} />
            <Fact label="Zone" value={incident.zone} />
            <Fact label="Coordinates" value={incident.location?.lat != null ? `${incident.location.lat.toFixed(4)}, ${incident.location.lng.toFixed(4)}` : '—'} />
          </dl>
        </section>

        {/* Rules */}
        {incident.rules_triggered?.length > 0 && (
          <section className="p-4">
            <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Rules Triggered</h4>
            <div className="space-y-1">
              {incident.rules_triggered.map(r => (
                <div key={r.name} className="flex items-center justify-between text-sm">
                  <span className="text-ink">{r.name}</span>
                  <SeverityChip severity={r.severity} />
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Stakeholders */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Stakeholders</h4>
          <StakeholderStatus stakeholders={incident.stakeholders} />
        </section>

        {/* Hardware */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Hardware</h4>
          <HardwareControl
            hardware={incident.hardware}
            incidentId={incident.incident_id}
            onOverride={onHardwareOverride}
          />
        </section>

        {/* Timeline */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Timeline</h4>
          <Timeline entries={incident.timeline} />
        </section>

        {/* Operator notes */}
        <section className="p-4">
          <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Operator Notes</h4>
          <textarea
            className="w-full border border-line rounded-md p-2 text-sm text-ink resize-none focus:outline-none focus:ring-1 focus:ring-brand"
            rows={3}
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Add notes…"
          />
        </section>
      </div>

      {/* Footer actions */}
      <div className="p-4 border-t border-line flex justify-between items-center gap-3">
        <button
          onClick={() => setConfirmDelete(true)}
          className="flex items-center gap-1.5 px-3 py-2 text-sm rounded border border-line bg-surface-alt hover:bg-line text-ink-muted hover:text-sev-critical font-medium transition-colors"
          title="Delete incident"
        >
          <Trash2 size={15} className="shrink-0" />
          <span>Delete</span>
        </button>

        {incident.status !== 'RESOLVED' && incident.status !== 'CLOSED' && (
          <button
            onClick={() => setConfirmClose(true)}
            className="px-4 py-2 text-sm rounded bg-brand text-white hover:bg-brand-hover font-medium ml-auto"
          >
            Close incident
          </button>
        )}
      </div>

      <ConfirmDialog
        open={confirmClose}
        title="Close incident"
        message={`Mark ${incident.incident_id} as closed? This action is logged.`}
        confirmLabel="Close incident"
        danger
        onConfirm={() => { onCloseIncident?.(incident.incident_id); setConfirmClose(false) }}
        onCancel={() => setConfirmClose(false)}
      />

      <ConfirmDialog
        open={confirmDelete}
        title="Delete incident"
        message={`Are you sure you want to permanently delete incident ${incident.incident_id}? This action cannot be undone.`}
        confirmLabel="Delete permanently"
        danger
        onConfirm={() => { onDeleteIncident?.(incident.incident_id); setConfirmDelete(false) }}
        onCancel={() => setConfirmDelete(false)}
      />
    </aside>
  )
}

function Fact({ label, value }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-ink font-medium">{value ?? '—'}</dd>
    </>
  )
}
