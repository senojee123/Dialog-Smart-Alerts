export default function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger = false, onConfirm, onCancel }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-lg p-6 max-w-sm w-full mx-4">
        <h3 className="font-semibold text-ink mb-2">{title}</h3>
        <p className="text-sm text-ink-muted mb-5">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm rounded border border-line text-ink hover:bg-surface-alt"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-sm rounded font-medium text-white ${danger ? 'bg-sev-critical hover:bg-red-700' : 'bg-brand hover:bg-brand-hover'}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
