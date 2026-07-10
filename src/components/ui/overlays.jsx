import { useEffect } from 'react'
import { X, AlertTriangle } from 'lucide-react'
import { Button } from './Button.jsx'

/** Close-on-Escape helper shared by overlays. */
function useEscape(active, onClose) {
  useEffect(() => {
    if (!active) return
    const h = e => e.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [active, onClose])
}

/**
 * Drawer — right-side slide-over panel (replaces the old SlideOver).
 */
export function Drawer({ open, onClose, title, description, footer, children, width = 'max-w-lg' }) {
  useEscape(open, onClose)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-drawer flex">
      <div className="flex-1 bg-black/30 animate-fade-in" onClick={onClose} />
      <div className={`w-full ${width} bg-white shadow-drawer flex flex-col overflow-hidden animate-slide-in`}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-line shrink-0">
          <div className="min-w-0">
            <h2 className="font-semibold text-ink truncate">{title}</h2>
            {description && <p className="text-xs text-ink-muted mt-0.5">{description}</p>}
          </div>
          <button onClick={onClose} className="text-ink-muted hover:text-ink p-1 -mr-1 rounded shrink-0">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-line shrink-0 bg-surface">{footer}</div>}
      </div>
    </div>
  )
}

/**
 * Modal — centred dialog.
 */
export function Modal({ open, onClose, title, children, footer, width = 'max-w-md' }) {
  useEscape(open, onClose)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center p-4 bg-black/40 animate-fade-in">
      <div className={`bg-white rounded-xl shadow-modal w-full ${width} overflow-hidden`} onClick={e => e.stopPropagation()}>
        {title && (
          <div className="flex items-center justify-between px-5 py-4 border-b border-line">
            <h2 className="font-semibold text-ink">{title}</h2>
            <button onClick={onClose} className="text-ink-muted hover:text-ink p-1 rounded"><X size={18} /></button>
          </div>
        )}
        <div className="p-5">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-line bg-surface flex justify-end gap-3">{footer}</div>}
      </div>
    </div>
  )
}

/**
 * ConfirmDialog — the single canonical confirm (replaces the two prior copies).
 */
export function ConfirmDialog({ open, title = 'Are you sure?', message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false, onConfirm, onCancel }) {
  useEscape(open, onCancel)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center p-4 bg-black/40 animate-fade-in">
      <div className="bg-white rounded-xl shadow-modal max-w-sm w-full p-6" onClick={e => e.stopPropagation()}>
        <div className="flex gap-3">
          {danger && (
            <div className="w-9 h-9 rounded-full bg-sev-critical/10 flex items-center justify-center shrink-0">
              <AlertTriangle size={18} className="text-sev-critical" />
            </div>
          )}
          <div className="min-w-0">
            <h3 className="font-semibold text-ink">{title}</h3>
            {message && <p className="text-sm text-ink-muted mt-1">{message}</p>}
          </div>
        </div>
        <div className="flex gap-3 justify-end mt-5">
          <Button variant="secondary" onClick={onCancel}>{cancelLabel}</Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  )
}
