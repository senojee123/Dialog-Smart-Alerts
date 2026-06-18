import { Bell, BellOff } from 'lucide-react'
import ModeBadge from './ModeBadge.jsx'
import HealthDot from './HealthDot.jsx'

const ENV = import.meta.env.VITE_ENV ?? 'dev'

export default function TopBar({ streamStatus, muteAlerts, onToggleMute }) {
  return (
    <header className="h-14 bg-maroon flex items-center px-4 gap-4 shrink-0 z-30">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-8 h-8 bg-brand rounded flex items-center justify-center text-white font-bold text-sm select-none">
          D
        </div>
        <span className="text-white font-semibold text-sm tracking-wide hidden sm:block">
          Dialog Smart Alerts
        </span>
      </div>

      <div className="flex items-center gap-3 ml-auto">
        {streamStatus === 'reconnecting' && (
          <span className="text-xs text-white/70 bg-white/10 px-2 py-0.5 rounded">
            Reconnecting…
          </span>
        )}
        {streamStatus === 'live' && (
          <span className="text-xs text-white/60">● live</span>
        )}

        <ModeBadge mode="LIVE" />

        {ENV !== 'prod' && (
          <span className="text-xs text-white/60 bg-white/10 px-2 py-0.5 rounded uppercase tracking-wider">
            {ENV}
          </span>
        )}

        <HealthDot />

        <button
          onClick={onToggleMute}
          className="text-white/70 hover:text-white"
          title={muteAlerts ? 'Unmute audible alerts' : 'Mute audible alerts'}
        >
          {muteAlerts ? <BellOff size={16} /> : <Bell size={16} />}
        </button>

        <span className="text-white/60 text-sm hidden md:block">Operator</span>
      </div>
    </header>
  )
}
