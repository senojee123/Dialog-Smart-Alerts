import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'

/**
 * ToastStack — bottom-right transient notifications.
 * Compatible with the useToast() hook: toasts = [{ id, message, type }].
 */
const TYPE_STYLES = {
  success: { cls: 'border-l-sev-low',      Icon: CheckCircle, iconCls: 'text-sev-low' },
  error:   { cls: 'border-l-sev-critical', Icon: AlertCircle, iconCls: 'text-sev-critical' },
  info:    { cls: 'border-l-ink',          Icon: Info,        iconCls: 'text-ink-muted' },
}

export function ToastStack({ toasts, onRemove }) {
  if (!toasts.length) return null
  return (
    <div className="fixed bottom-4 right-4 z-toast flex flex-col gap-2 max-w-sm">
      {toasts.map(t => {
        const { cls, Icon, iconCls } = TYPE_STYLES[t.type] ?? TYPE_STYLES.info
        return (
          <div key={t.id}
               className={`flex items-start gap-3 px-4 py-3 rounded-lg bg-white border border-line border-l-4 shadow-modal animate-slide-in ${cls}`}>
            <Icon size={16} className={`mt-0.5 shrink-0 ${iconCls}`} />
            <span className="text-sm flex-1 text-ink">{t.message}</span>
            <button onClick={() => onRemove(t.id)} className="text-ink-subtle hover:text-ink">
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default ToastStack
