import { Siren, AlertTriangle, AlertCircle, Info } from 'lucide-react'

/**
 * Status & severity indicators — the single source of severity/state colour.
 * Severity colour now flows from Tailwind tokens (bg-sev-*), not inline hex,
 * so SeverityChip and everything else agree.
 */

// ── Badge — small labelled token ──────────────────────────────────────────────
const BADGE_COLORS = {
  gray:   'bg-surface-alt text-ink-muted',
  green:  'bg-sev-low/10 text-sev-low',
  red:    'bg-sev-critical/10 text-sev-critical',
  amber:  'bg-sev-medium/15 text-ink',
  orange: 'bg-orange/10 text-orange',
  blue:   'bg-blue-50 text-blue-700',
  brand:  'bg-brand-subtle text-brand',
}

export function Badge({ children, color = 'gray', className = '' }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${BADGE_COLORS[color]} ${className}`}>
      {children}
    </span>
  )
}

// ── SeverityChip ──────────────────────────────────────────────────────────────
export const SEV_UI = {
  CRITICAL: { cls: 'bg-sev-critical text-white', icon: Siren,         label: 'Critical' },
  HIGH:     { cls: 'bg-sev-high text-white',     icon: AlertTriangle, label: 'High' },
  MEDIUM:   { cls: 'bg-sev-medium text-ink',     icon: AlertCircle,   label: 'Medium' },
  LOW:      { cls: 'bg-sev-low text-white',      icon: Info,          label: 'Low' },
}

export function SeverityChip({ severity, pulse = false, size = 'sm' }) {
  const meta = SEV_UI[severity]
  if (!meta) return null
  const Icon = meta.icon
  const dims = size === 'lg' ? 'px-3 py-1.5 text-sm' : 'px-2 py-0.5 text-xs'
  return (
    <span className={`inline-flex items-center gap-1.5 font-semibold rounded-md ${dims} ${meta.cls} ${pulse ? 'critical-pulse' : ''}`}>
      <Icon size={size === 'lg' ? 14 : 12} />
      {meta.label}
    </span>
  )
}

// ── StatusBadge — incident lifecycle + hardware states ────────────────────────
const STATUS_STYLES = {
  ACTIVE:          'bg-sev-critical/10 text-sev-critical border-sev-critical/30',
  OPERATOR_REVIEW: 'bg-orange/10 text-orange border-orange/30',
  RESOLVED:        'bg-sev-low/10 text-sev-low border-sev-low/30',
  CLOSED:          'bg-surface-alt text-ink-muted border-line',

  ON:              'bg-hw-on/10 text-hw-on border-hw-on/30',
  OFF:             'bg-surface-alt text-ink-muted border-line',
  OFFLINE:         'bg-hw-offline/10 text-hw-offline border-hw-offline/30',
  ERROR:           'bg-hw-error/10 text-hw-error border-hw-error/30',
  MANUAL_OVERRIDE: 'bg-maroon/10 text-maroon border-maroon/30',
}

export function StatusBadge({ status }) {
  const cls = STATUS_STYLES[status] ?? 'bg-surface-alt text-ink-muted border-line'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded-md border ${cls}`}>
      {status?.replace(/_/g, ' ')}
    </span>
  )
}

// ── StatusDot — online / offline inline indicator ─────────────────────────────
export function StatusDot({ online, label }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={`w-2 h-2 rounded-full ${online ? 'bg-sev-low' : 'bg-ink-subtle'}`} />
      {label ?? (online ? 'Online' : 'Offline')}
    </span>
  )
}
