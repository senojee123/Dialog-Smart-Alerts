const STATUS_STYLES = {
  ACTIVE:          'bg-sev-critical/10 text-sev-critical border-sev-critical/30',
  OPERATOR_REVIEW: 'bg-orange/10 text-orange border-orange/30',
  RESOLVED:        'bg-sev-low/10 text-sev-low border-sev-low/30',
  CLOSED:          'bg-surface-alt text-ink-muted border-line',

  ON:              'bg-sev-low/10 text-sev-low border-sev-low/30',
  OFF:             'bg-surface-alt text-ink-muted border-line',
  OFFLINE:         'bg-sev-critical/10 text-sev-critical border-sev-critical/30',
  ERROR:           'bg-sev-critical/10 text-sev-critical border-sev-critical/30',
  MANUAL_OVERRIDE: 'bg-maroon/10 text-maroon border-maroon/30',
}

export default function StatusBadge({ status }) {
  const cls = STATUS_STYLES[status] ?? 'bg-surface-alt text-ink-muted border-line'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded border ${cls}`}>
      {status?.replace(/_/g, ' ')}
    </span>
  )
}
