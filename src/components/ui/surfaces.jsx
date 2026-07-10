/**
 * Surfaces & layout — Card, Panel, Section, PageHeader, EmptyState, Skeleton.
 * The "Elevated Dialog" look: light surface canvas, white cards with a hairline
 * border + soft shadow.
 */

export function Card({ children, className = '', padded = true, hover = false, ...props }) {
  return (
    <div
      className={`bg-white border border-line rounded-lg shadow-card ${padded ? 'p-4' : ''}
                  ${hover ? 'transition-shadow hover:shadow-popover' : ''} ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}

/** A flat, bordered grouping with an optional title — for nested config blocks. */
export function Panel({ title, action, children, className = '' }) {
  return (
    <div className={`bg-surface border border-line rounded-lg ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          {title && <h3 className="text-sm font-semibold text-ink">{title}</h3>}
          {action}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  )
}

/** A titled content section with a small uppercase label (used in drawers/detail). */
export function Section({ title, action, children, className = '' }) {
  return (
    <section className={className}>
      {(title || action) && (
        <div className="flex items-center justify-between mb-3">
          {title && <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wide">{title}</h4>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

/** Page header band — title + description + right-aligned actions. */
export function PageHeader({ title, description, action, icon: Icon, className = '' }) {
  return (
    <div className={`px-6 py-4 border-b border-line bg-white shrink-0 flex items-center justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-ink flex items-center gap-2">
          {Icon && <Icon size={18} className="text-brand shrink-0" />}
          <span className="truncate">{title}</span>
        </h1>
        {description && <p className="text-sm text-ink-muted mt-0.5">{description}</p>}
      </div>
      {action && <div className="flex items-center gap-2 shrink-0">{action}</div>}
    </div>
  )
}

export function EmptyState({ icon: Icon, title, description, action, className = '' }) {
  return (
    <div className={`flex flex-col items-center justify-center text-center py-16 px-6 ${className}`}>
      {Icon && (
        <div className="w-12 h-12 rounded-full bg-surface-alt flex items-center justify-center mb-3">
          <Icon size={22} className="text-ink-subtle" />
        </div>
      )}
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="text-sm text-ink-muted mt-1 max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Skeleton({ className = '' }) {
  return <div className={`bg-surface-alt rounded animate-pulse ${className}`} />
}

export function SkeletonRows({ rows = 5, className = '' }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}
