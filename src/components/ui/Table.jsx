import { Button } from './Button.jsx'
import { EmptyState } from './surfaces.jsx'

/**
 * Table — declarative columns + rows, with optional row actions.
 * columns: [{ key, label, render?(row), align? }]
 */
export function Table({ columns, rows, onEdit, onDelete, onRowClick, selectedId, emptyMessage = 'No records yet.', emptyIcon }) {
  const hasActions = onEdit || onDelete
  if (rows.length === 0) {
    return <EmptyState icon={emptyIcon} title={emptyMessage} />
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line bg-surface-alt/40">
            {columns.map(c => (
              <th key={c.key}
                  className={`px-4 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wide whitespace-nowrap
                              ${c.align === 'right' ? 'text-right' : 'text-left'}`}>
                {c.label}
              </th>
            ))}
            {hasActions && <th className="px-4 py-2.5 text-right text-xs font-semibold text-ink-muted uppercase tracking-wide">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.id ?? i}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`border-b border-line transition-colors
                ${onRowClick ? 'cursor-pointer' : ''}
                ${selectedId && row.id === selectedId ? 'bg-brand-subtle/60' : 'hover:bg-surface-alt/50'}`}
            >
              {columns.map(c => (
                <td key={c.key} className={`px-4 py-3 text-ink align-middle ${c.align === 'right' ? 'text-right' : ''}`}>
                  {c.render ? c.render(row) : row[c.key] ?? <span className="text-ink-subtle">—</span>}
                </td>
              ))}
              {hasActions && (
                <td className="px-4 py-3 text-right whitespace-nowrap" onClick={e => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1">
                    {onEdit && <Button variant="ghost" size="sm" onClick={() => onEdit(row)}>Edit</Button>}
                    {onDelete && (
                      <Button variant="ghost" size="sm" onClick={() => onDelete(row)}
                              className="text-sev-critical hover:bg-sev-critical/5">Delete</Button>
                    )}
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
