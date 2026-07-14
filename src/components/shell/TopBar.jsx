import { Bell, BellOff, Menu } from 'lucide-react'
import ModeBadge from './ModeBadge.jsx'
import HealthDot from './HealthDot.jsx'
import dialogLogo from '../../assets/dialog-logo.jpg'

const ENV = import.meta.env.VITE_ENV ?? 'dev'

export default function TopBar({ streamStatus, muteAlerts, onToggleMute, onToggleSidebar }) {
  return (
    <header className="h-14 bg-maroon flex items-center px-4 gap-4 shrink-0 z-30">
      <button
        onClick={onToggleSidebar}
        className="text-white/70 hover:text-white mr-1 p-1 hover:bg-white/10 rounded transition-colors"
        title="Toggle Sidebar"
      >
        <Menu size={20} />
      </button>
      <div className="flex items-center gap-3 min-w-0">
        <img src={dialogLogo} alt="Dialog 5G Ultra" className="h-8 rounded object-contain bg-white px-2 py-0.5" />
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
