import { Check } from 'lucide-react'

/**
 * Stepper — horizontal numbered progress with clickable visited steps.
 * steps:      [{ label, sublabel? }] or [string]
 * current:    active index
 * maxReached: furthest index the user has reached (steps ≤ this are clickable)
 */
export function Stepper({ steps, current, maxReached = current, onStepClick, className = '' }) {
  const items = steps.map(s => (typeof s === 'string' ? { label: s } : s))
  return (
    <div className={`flex items-center gap-1 overflow-x-auto ${className}`}>
      {items.map((step, i) => {
        const done = i < current
        const active = i === current
        const clickable = i <= maxReached
        return (
          <div key={step.label} className="flex items-center shrink-0">
            <button
              disabled={!clickable}
              onClick={() => clickable && onStepClick?.(i)}
              className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg transition-colors
                ${clickable ? 'cursor-pointer hover:bg-surface-alt' : 'cursor-default'}`}
            >
              <span className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-semibold shrink-0 transition-colors
                ${done ? 'bg-sev-low text-white'
                  : active ? 'bg-brand text-white ring-4 ring-brand/15'
                  : 'bg-surface-alt text-ink-muted border border-line'}`}>
                {done ? <Check size={14} /> : i + 1}
              </span>
              <span className="text-left">
                <span className={`block text-sm leading-tight whitespace-nowrap ${active ? 'text-ink font-semibold' : 'text-ink-muted'}`}>
                  {step.label}
                </span>
                {step.sublabel && <span className="block text-[11px] text-ink-subtle whitespace-nowrap">{step.sublabel}</span>}
              </span>
            </button>
            {i < items.length - 1 && (
              <div className={`w-8 h-px mx-1 ${done ? 'bg-sev-low/40' : 'bg-line'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}
