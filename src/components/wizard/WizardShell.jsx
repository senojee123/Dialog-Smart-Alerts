import { Check } from 'lucide-react'
import { Btn } from '../admin/CrudShell.jsx'

export function WizardProgress({ steps, current, onStepClick, maxReached }) {
  return (
    <div className="flex items-center gap-1 px-6 py-4 border-b border-line bg-white overflow-x-auto">
      {steps.map((label, i) => {
        const done    = i < current
        const active  = i === current
        const clickable = i <= maxReached
        return (
          <div key={label} className="flex items-center shrink-0">
            <button
              disabled={!clickable}
              onClick={() => clickable && onStepClick?.(i)}
              className={`flex items-center gap-2 px-2 py-1 rounded-md transition-colors
                ${clickable ? 'cursor-pointer hover:bg-surface-alt' : 'cursor-default'}`}
            >
              <span className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold shrink-0
                ${done ? 'bg-sev-low text-white'
                  : active ? 'bg-brand text-white'
                  : 'bg-surface-alt text-ink-muted'}`}>
                {done ? <Check size={13} /> : i + 1}
              </span>
              <span className={`text-sm whitespace-nowrap ${active ? 'text-ink font-semibold' : 'text-ink-muted'}`}>
                {label}
              </span>
            </button>
            {i < steps.length - 1 && <div className="w-6 h-px bg-line mx-1" />}
          </div>
        )
      })}
    </div>
  )
}

export function WizardFooter({ onBack, onNext, backLabel = 'Back', nextLabel = 'Next', nextDisabled, busy, canBack = true, hint }) {
  return (
    <div className="border-t border-line bg-white px-6 py-3 flex items-center justify-between shrink-0">
      <div className="text-xs text-ink-muted">{hint}</div>
      <div className="flex gap-3">
        {canBack && <Btn variant="secondary" onClick={onBack} disabled={busy}>{backLabel}</Btn>}
        <Btn variant="primary" onClick={onNext} disabled={nextDisabled || busy}>
          {busy ? 'Working…' : nextLabel}
        </Btn>
      </div>
    </div>
  )
}

export function StepHeading({ title, description }) {
  return (
    <div className="mb-5">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      {description && <p className="text-sm text-ink-muted mt-1">{description}</p>}
    </div>
  )
}
