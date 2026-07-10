/**
 * Tabs — underline-style tab bar.
 * tabs: [{ value, label, icon?, count? }]
 */
export function Tabs({ tabs, value, onChange, className = '' }) {
  return (
    <div className={`flex items-center gap-1 border-b border-line ${className}`}>
      {tabs.map(tab => {
        const active = tab.value === value
        const Icon = tab.icon
        return (
          <button
            key={tab.value}
            onClick={() => onChange(tab.value)}
            className={`relative inline-flex items-center gap-1.5 px-3.5 py-2.5 text-sm font-medium transition-colors
              ${active ? 'text-brand' : 'text-ink-muted hover:text-ink'}`}
          >
            {Icon && <Icon size={15} />}
            {tab.label}
            {tab.count != null && (
              <span className={`ml-1 px-1.5 py-0.5 rounded text-[11px] font-semibold
                ${active ? 'bg-brand-subtle text-brand' : 'bg-surface-alt text-ink-muted'}`}>
                {tab.count}
              </span>
            )}
            {active && <span className="absolute left-0 right-0 -bottom-px h-0.5 bg-brand rounded-full" />}
          </button>
        )
      })}
    </div>
  )
}
