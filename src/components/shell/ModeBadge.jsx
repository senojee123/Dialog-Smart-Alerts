export default function ModeBadge({ mode = 'SHADOW' }) {
  const isLive = mode === 'LIVE'
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold tracking-wide
        ${isLive ? 'bg-sev-critical text-white' : 'bg-ink-muted text-white'}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${isLive ? 'bg-white animate-pulse-sev' : 'bg-white/60'}`} />
      {mode}
    </span>
  )
}
