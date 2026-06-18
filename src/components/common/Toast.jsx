import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'

const TYPE_STYLES = {
  success: { cls: 'bg-sev-low text-white', Icon: CheckCircle },
  error:   { cls: 'bg-sev-critical text-white', Icon: AlertCircle },
  info:    { cls: 'bg-ink text-white', Icon: Info },
}

export default function ToastStack({ toasts, onRemove }) {
  if (!toasts.length) return null
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map(t => {
        const { cls, Icon } = TYPE_STYLES[t.type] ?? TYPE_STYLES.info
        return (
          <div key={t.id} className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg ${cls}`}>
            <Icon size={16} className="mt-0.5 shrink-0" />
            <span className="text-sm flex-1">{t.message}</span>
            <button onClick={() => onRemove(t.id)} className="opacity-70 hover:opacity-100">
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
