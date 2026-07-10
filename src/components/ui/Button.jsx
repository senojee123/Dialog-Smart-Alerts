import { Loader2 } from 'lucide-react'

/**
 * Button — the one canonical button for the whole app.
 * variants: primary | secondary | danger | ghost | subtle
 * sizes:    sm | md | lg
 */
const VARIANTS = {
  primary:   'bg-brand text-white hover:bg-brand-hover shadow-sm',
  secondary: 'bg-white border border-line text-ink hover:bg-surface-alt',
  danger:    'bg-sev-critical text-white hover:opacity-90 shadow-sm',
  ghost:     'text-ink-muted hover:text-ink hover:bg-surface-alt',
  subtle:    'bg-surface-alt text-ink hover:bg-surface-sunken',
}

const SIZES = {
  sm: 'px-2.5 py-1.5 text-xs gap-1.5 rounded-md',
  md: 'px-3.5 py-2 text-sm gap-2 rounded-lg',
  lg: 'px-5 py-2.5 text-sm gap-2 rounded-lg',
}

export function Button({ children, variant = 'primary', size = 'md', loading = false, className = '', ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center font-medium transition-colors
                  disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none
                  ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  )
}

/** Square icon-only button. */
export function IconButton({ icon: Icon, label, variant = 'ghost', size = 16, className = '', ...props }) {
  const pad = { 14: 'p-1.5', 16: 'p-2', 18: 'p-2', 20: 'p-2.5' }[size] || 'p-2'
  return (
    <button
      aria-label={label}
      title={label}
      className={`inline-flex items-center justify-center rounded-lg transition-colors focus:outline-none
                  ${VARIANTS[variant]} ${pad} ${className}`}
      {...props}
    >
      <Icon size={size} />
    </button>
  )
}

export function Spinner({ size = 16, className = '' }) {
  return <Loader2 size={size} className={`animate-spin ${className}`} />
}
