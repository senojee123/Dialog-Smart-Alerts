/**
 * Form primitives — Field wrapper + inputs, all sharing one focus/border style.
 */

const CONTROL =
  'w-full px-3 py-2 text-sm border border-line rounded-md bg-white text-ink transition-shadow ' +
  'focus:outline-none focus:ring-2 focus:ring-brand/25 focus:border-brand ' +
  'placeholder:text-ink-subtle disabled:bg-surface-alt disabled:text-ink-muted disabled:cursor-not-allowed'

export function Field({ label, required, hint, error, children, className = '' }) {
  return (
    <div className={`space-y-1.5 ${className}`}>
      {label && (
        <label className="block text-sm font-medium text-ink">
          {label}{required && <span className="text-sev-critical ml-0.5">*</span>}
        </label>
      )}
      {children}
      {error
        ? <p className="text-xs text-sev-critical">{error}</p>
        : hint && <p className="text-xs text-ink-muted">{hint}</p>}
    </div>
  )
}

export function Input({ className = '', ...props }) {
  return <input className={`${CONTROL} ${className}`} {...props} />
}

export function Textarea({ className = '', rows = 3, ...props }) {
  return <textarea rows={rows} className={`${CONTROL} resize-none ${className}`} {...props} />
}

export function Select({ children, className = '', ...props }) {
  return <select className={`${CONTROL} ${className}`} {...props}>{children}</select>
}

export function Checkbox({ label, hint, checked, onChange, className = '', ...props }) {
  return (
    <label className={`flex items-start gap-2.5 cursor-pointer ${className}`}>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="mt-0.5 rounded border-line accent-brand w-4 h-4 shrink-0"
        {...props}
      />
      <span className="text-sm text-ink leading-tight">
        {label}
        {hint && <span className="block text-xs text-ink-muted mt-0.5">{hint}</span>}
      </span>
    </label>
  )
}

/** iOS-style toggle for boolean settings. */
export function Toggle({ checked, onChange, label, className = '' }) {
  return (
    <label className={`inline-flex items-center gap-2.5 cursor-pointer select-none ${className}`}>
      <span
        onClick={() => onChange?.(!checked)}
        className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${checked ? 'bg-brand' : 'bg-line-strong'}`}
      >
        <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-transform
                          ${checked ? 'translate-x-4' : ''}`} />
      </span>
      {label && <span className="text-sm text-ink">{label}</span>}
    </label>
  )
}

/**
 * SegmentedControl — replaces the ad-hoc grid/map + table/map toggles.
 * options: [{ value, label, icon? }]
 */
export function SegmentedControl({ options, value, onChange, size = 'md', className = '' }) {
  const pad = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm'
  return (
    <div className={`inline-flex border border-line rounded-lg overflow-hidden bg-white ${className}`}>
      {options.map(opt => {
        const active = opt.value === value
        const Icon = opt.icon
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`inline-flex items-center gap-1.5 font-medium transition-colors ${pad}
              ${active ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}
          >
            {Icon && <Icon size={14} />}
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
