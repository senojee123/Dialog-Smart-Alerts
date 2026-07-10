import { AlertCircle, Info, CheckCircle, AlertTriangle } from 'lucide-react'
import { Button } from './Button.jsx'

/**
 * Banner — inline contextual message (error / info / success / warning).
 */
const VARIANTS = {
  error:   { cls: 'bg-sev-critical/5 border-sev-critical/20 text-sev-critical', Icon: AlertCircle },
  warning: { cls: 'bg-orange/5 border-orange/25 text-orange',                   Icon: AlertTriangle },
  info:    { cls: 'bg-blue-50 border-blue-100 text-blue-700',                    Icon: Info },
  success: { cls: 'bg-sev-low/5 border-sev-low/20 text-sev-low',                Icon: CheckCircle },
}

export function Banner({ variant = 'info', title, children, action, className = '' }) {
  const { cls, Icon } = VARIANTS[variant] ?? VARIANTS.info
  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-lg border text-sm ${cls} ${className}`}>
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={title ? 'mt-0.5 opacity-90' : ''}>{children}</div>}
      </div>
      {action}
    </div>
  )
}

/** ErrorBanner — back-compat thin wrapper used by admin forms. */
export function ErrorBanner({ error }) {
  if (!error) return null
  return <Banner variant="error" className="mb-4">{error}</Banner>
}

/** SaveBar — cancel/save footer for forms in drawers. */
export function SaveBar({ onSave, onCancel, saving, label = 'Save' }) {
  return (
    <div className="flex justify-end gap-3 pt-4 border-t border-line mt-4">
      <Button variant="secondary" onClick={onCancel} disabled={saving}>Cancel</Button>
      <Button variant="primary" onClick={onSave} loading={saving}>{label}</Button>
    </div>
  )
}
