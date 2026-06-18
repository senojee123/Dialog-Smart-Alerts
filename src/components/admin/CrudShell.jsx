/**
 * Reusable admin page shell: header + action bar + table + slide-over form panel.
 */
import { X } from 'lucide-react'

export function PageHeader({ title, description, action }) {
  return (
    <div className="px-6 py-4 border-b border-line bg-white shrink-0 flex items-center justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description && <p className="text-sm text-ink-muted mt-0.5">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function Btn({ children, variant = 'primary', size = 'md', ...props }) {
  const base = 'inline-flex items-center gap-1.5 font-medium rounded-lg transition-colors disabled:opacity-50'
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm', lg: 'px-5 py-2.5 text-sm' }
  const variants = {
    primary:   'bg-brand text-white hover:bg-brand-hover',
    secondary: 'bg-surface border border-line text-ink hover:bg-surface-alt',
    danger:    'bg-sev-critical text-white hover:opacity-90',
    ghost:     'text-ink-muted hover:text-ink hover:bg-surface-alt',
  }
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]}`} {...props}>
      {children}
    </button>
  )
}

export function Badge({ children, color = 'gray' }) {
  const colors = {
    gray:   'bg-surface-alt text-ink-muted',
    green:  'bg-sev-low/10 text-sev-low',
    red:    'bg-sev-critical/10 text-sev-critical',
    amber:  'bg-sev-medium/10 text-ink',
    blue:   'bg-blue-50 text-blue-700',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors[color]}`}>
      {children}
    </span>
  )
}

export function StatusDot({ online }) {
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <span className={`w-2 h-2 rounded-full ${online ? 'bg-sev-low' : 'bg-ink-muted/40'}`} />
      {online ? 'Online' : 'Offline'}
    </span>
  )
}

export function SlideOver({ open, onClose, title, children }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/30" onClick={onClose} />
      {/* Panel */}
      <div className="w-full max-w-lg bg-white shadow-xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line shrink-0">
          <h2 className="font-semibold text-ink">{title}</h2>
          <button onClick={onClose} className="text-ink-muted hover:text-ink p-1 rounded">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, required, children, hint }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-ink">
        {label}{required && <span className="text-sev-critical ml-0.5">*</span>}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-muted">{hint}</p>}
    </div>
  )
}

export function Input({ ...props }) {
  return (
    <input
      className="w-full px-3 py-2 text-sm border border-line rounded-lg bg-white text-ink
                 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand
                 placeholder:text-ink-muted/60"
      {...props}
    />
  )
}

export function Select({ children, ...props }) {
  return (
    <select
      className="w-full px-3 py-2 text-sm border border-line rounded-lg bg-white text-ink
                 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
      {...props}
    >
      {children}
    </select>
  )
}

export function Textarea({ ...props }) {
  return (
    <textarea
      rows={3}
      className="w-full px-3 py-2 text-sm border border-line rounded-lg bg-white text-ink
                 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand
                 placeholder:text-ink-muted/60 resize-none"
      {...props}
    />
  )
}

export function Table({ columns, rows, onEdit, onDelete, emptyMessage = 'No records yet.' }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            {columns.map(c => (
              <th key={c.key} className="px-4 py-3 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide whitespace-nowrap">
                {c.label}
              </th>
            ))}
            <th className="px-4 py-3 text-right text-xs font-semibold text-ink-muted uppercase tracking-wide">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1} className="px-4 py-12 text-center text-ink-muted text-sm">
                {emptyMessage}
              </td>
            </tr>
          )}
          {rows.map((row, i) => (
            <tr key={row.id ?? i} className="border-b border-line hover:bg-surface-alt/50 transition-colors">
              {columns.map(c => (
                <td key={c.key} className="px-4 py-3 text-ink align-middle">
                  {c.render ? c.render(row) : row[c.key] ?? <span className="text-ink-muted">—</span>}
                </td>
              ))}
              <td className="px-4 py-3 text-right whitespace-nowrap">
                <div className="flex items-center justify-end gap-1">
                  {onEdit && (
                    <Btn variant="ghost" size="sm" onClick={() => onEdit(row)}>Edit</Btn>
                  )}
                  {onDelete && (
                    <Btn variant="ghost" size="sm" onClick={() => onDelete(row)}
                         className="text-sev-critical hover:bg-sev-critical/5">Delete</Btn>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ConfirmDialog({ open, message, onConfirm, onCancel }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-sm w-full">
        <p className="text-ink text-sm mb-5">{message}</p>
        <div className="flex gap-3 justify-end">
          <Btn variant="secondary" onClick={onCancel}>Cancel</Btn>
          <Btn variant="danger" onClick={onConfirm}>Delete</Btn>
        </div>
      </div>
    </div>
  )
}

export function SaveBar({ onSave, onCancel, saving, label = 'Save' }) {
  return (
    <div className="flex justify-end gap-3 pt-4 border-t border-line mt-4">
      <Btn variant="secondary" onClick={onCancel} disabled={saving}>Cancel</Btn>
      <Btn variant="primary" onClick={onSave} disabled={saving}>
        {saving ? 'Saving…' : label}
      </Btn>
    </div>
  )
}

export function ErrorBanner({ error }) {
  if (!error) return null
  return (
    <div className="mb-4 px-4 py-3 rounded-lg bg-sev-critical/10 text-sev-critical text-sm border border-sev-critical/20">
      {error}
    </div>
  )
}
