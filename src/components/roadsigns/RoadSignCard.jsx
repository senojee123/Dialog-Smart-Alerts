import { WifiOff, AlertTriangle } from 'lucide-react'
import { relativeTime } from '../../lib/format.js'

export const SIGN_STATE = {
  WARNING: {
    color:     '#D92D20',
    glow:      'rgba(217,45,32,0.7)',
    ringColor: '#D92D20',
    label:     'WILDLIFE CROSSING',
    sub:       'STOP / SLOW DOWN',
    pulse:     true,
    dotColor:  'bg-sev-critical',
  },
  CAUTION: {
    color:     '#F2841C',
    glow:      'rgba(242,132,28,0.55)',
    ringColor: '#F2841C',
    label:     'WILDLIFE NEARBY',
    sub:       'SLOW DOWN',
    pulse:     false,
    dotColor:  'bg-sev-medium',
  },
  CLEAR: {
    color:     '#2a2a2a',
    glow:      'none',
    ringColor: '#222',
    label:     'ROAD CLEAR',
    sub:       '',
    pulse:     false,
    dotColor:  'bg-sev-low',
  },
  OFFLINE: {
    color:     '#444',
    glow:      'none',
    ringColor: '#333',
    label:     'OFFLINE',
    sub:       '',
    pulse:     false,
    dotColor:  'bg-ink-muted',
  },
}

export default function RoadSignCard({ sign, derivedState, nearbyIncident, onSelect, selected }) {
  const cfg     = SIGN_STATE[derivedState] ?? SIGN_STATE.CLEAR
  const isLit   = derivedState === 'WARNING' || derivedState === 'CAUTION'
  const isOff   = derivedState === 'OFFLINE'

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left rounded-xl border-2 overflow-hidden transition-all focus:outline-none
        ${selected ? 'border-brand' : 'border-line hover:border-ink-muted'}`}
    >
      {/* LED board panel */}
      <div
        className="relative flex flex-col items-center justify-center py-6 px-4 gap-3"
        style={{
          background: '#0d0d0d',
          boxShadow: isLit ? `inset 0 0 40px rgba(0,0,0,0.8), 0 0 24px ${cfg.glow}` : 'none',
        }}
      >
        {/* Offline overlay */}
        {isOff && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
            <WifiOff size={24} className="text-ink-muted" />
          </div>
        )}

        {/* Elephant silhouette */}
        <div
          className={cfg.pulse ? 'animate-pulse-sev' : ''}
          style={{
            filter: isLit ? `drop-shadow(0 0 16px ${cfg.color}) drop-shadow(0 0 6px ${cfg.color})` : 'none',
            color: isLit ? cfg.color : '#2a2a2a',
            fontSize: '56px',
            lineHeight: 1,
            userSelect: 'none',
          }}
        >
          🐘
        </div>

        {/* State label */}
        <div className="text-center">
          <div
            className="font-bold tracking-widest text-xs"
            style={{ color: isLit ? cfg.color : '#444', letterSpacing: '0.18em' }}
          >
            {cfg.label}
          </div>
          {cfg.sub && (
            <div
              className="text-xs mt-0.5 tracking-wider"
              style={{ color: isLit ? `${cfg.color}cc` : '#333' }}
            >
              {cfg.sub}
            </div>
          )}
        </div>

        {/* Outer LED ring border */}
        <div
          className="absolute inset-0 rounded-none pointer-events-none"
          style={{
            border: `2px solid ${isLit ? cfg.ringColor : '#1a1a1a'}`,
            opacity: isLit ? 0.6 : 0.3,
          }}
        />
      </div>

      {/* Info panel */}
      <div className="bg-white px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-ink">{sign.name}</span>
              <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dotColor}`} />
            </div>
            <div className="text-xs text-ink-muted mt-0.5 truncate">
              {sign.road} · km {sign.km_marker}
            </div>
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
