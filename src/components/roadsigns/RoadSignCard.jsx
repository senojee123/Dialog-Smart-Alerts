import { WifiOff, AlertTriangle, Check } from 'lucide-react'
import { relativeTime } from '../../lib/format.js'

// State → LED styling. Labels are generic; the detected object name (when known)
// is layered on top so the same board works for any use case, not just wildlife.
export const SIGN_STATE = {
  WARNING: { color: '#D92D20', glow: 'rgba(217,45,32,0.7)',  ringColor: '#D92D20', label: 'HAZARD AHEAD', sub: 'STOP / SLOW DOWN', pulse: true,  dotColor: 'bg-sev-critical' },
  CAUTION: { color: '#F2841C', glow: 'rgba(242,132,28,0.55)', ringColor: '#F2841C', label: 'CAUTION',      sub: 'SLOW DOWN',        pulse: false, dotColor: 'bg-sev-medium' },
  CLEAR:   { color: '#22c55e', glow: 'none',                  ringColor: '#222',    label: 'ROAD CLEAR',   sub: '',                 pulse: false, dotColor: 'bg-sev-low' },
  OFFLINE: { color: '#444',    glow: 'none',                  ringColor: '#333',    label: 'OFFLINE',      sub: '',                 pulse: false, dotColor: 'bg-ink-muted' },
}

export default function RoadSignCard({ sign, derivedState, nearbyIncident, onSelect, selected }) {
  const cfg   = SIGN_STATE[derivedState] ?? SIGN_STATE.CLEAR
  const isLit = derivedState === 'WARNING' || derivedState === 'CAUTION'
  const isOff = derivedState === 'OFFLINE'
  const object = nearbyIncident?.object

  // Headline derived from the actual detected object when available.
  const headline = !isLit ? cfg.label
    : object ? `${String(object).toUpperCase()} ${derivedState === 'WARNING' ? 'CROSSING' : 'NEARBY'}`
    : cfg.label
  const Glyph = isOff ? WifiOff : isLit ? AlertTriangle : Check

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left rounded-xl border-2 overflow-hidden transition-all focus:outline-none shadow-card
        ${selected ? 'border-brand' : 'border-line hover:border-ink-muted'}`}
    >
      {/* LED board panel */}
      <div className="relative flex flex-col items-center justify-center py-6 px-4 gap-3"
           style={{ background: '#0d0d0d', boxShadow: isLit ? `inset 0 0 40px rgba(0,0,0,0.8), 0 0 24px ${cfg.glow}` : 'none' }}>
        {isOff && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
            <WifiOff size={24} className="text-ink-muted" />
          </div>
        )}

        <div className={cfg.pulse ? 'animate-pulse-sev' : ''}>
          <Glyph size={48} color={isLit ? cfg.color : derivedState === 'CLEAR' ? '#22c55e' : '#2e2e2e'}
            style={{ filter: isLit ? `drop-shadow(0 0 10px ${cfg.color}) drop-shadow(0 0 4px ${cfg.color})` : 'none' }} />
        </div>

        <div className="text-center">
          <div className="font-bold tracking-widest text-xs" style={{ color: isLit ? cfg.color : '#444', letterSpacing: '0.18em' }}>
            {headline}
          </div>
          {cfg.sub && (
            <div className="text-xs mt-0.5 tracking-wider" style={{ color: isLit ? `${cfg.color}cc` : '#333' }}>{cfg.sub}</div>
          )}
        </div>

        <div className="absolute inset-0 pointer-events-none"
             style={{ border: `2px solid ${isLit ? cfg.ringColor : '#1a1a1a'}`, opacity: isLit ? 0.6 : 0.3 }} />
      </div>

      {/* Info panel */}
      <div className="bg-white px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-ink">{sign.name}</span>
              <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dotColor}`} />
            </div>
            <div className="text-xs text-ink-muted mt-0.5 truncate">{sign.road}{sign.km_marker != null ? ` · km ${sign.km_marker}` : ''}</div>
            <div className="text-xs text-ink-muted">{sign.zone}</div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-xs text-ink-muted">{sign.id}</div>
            <div className="text-xs text-ink-muted mt-0.5">{relativeTime(sign.last_updated)}</div>
          </div>
        </div>

        {nearbyIncident && (
          <div className="mt-2 flex items-center gap-1.5 text-xs text-sev-critical font-medium">
            <AlertTriangle size={11} />
            {nearbyIncident.incident_id} · {nearbyIncident.object}
          </div>
        )}
      </div>
    </button>
  )
}
