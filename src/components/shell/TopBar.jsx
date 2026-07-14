import { Bell, BellOff, Menu } from 'lucide-react'
import ModeBadge from './ModeBadge.jsx'
import HealthDot from './HealthDot.jsx'
import dialogLogo from '../../assets/dialog-logo.jpg'

const ENV = import.meta.env.VITE_ENV ?? 'dev'

export default function TopBar({ streamStatus, muteAlerts, onToggleMute, onToggleSidebar }) {
  return (
    <header className="h-14 bg-brand/[0.04] border-b border-line flex items-center px-4 gap-4 shrink-0 z-30">
      <button
        onClick={onToggleSidebar}
        className="text-ink-muted hover:text-ink mr-1 p-1 hover:bg-line/50 rounded transition-colors"
        title="Toggle Sidebar"
      >
        <Menu size={20} />
      </button>
      <div className="flex items-center gap-3 min-w-0">
        <img src={dialogLogo} alt="Dialog 5G Ultra" className="h-8 rounded object-contain bg-white border border-line px-2 py-0.5" />
        <span className="text-ink font-semibold text-sm tracking-wide hidden sm:block">
          Dialog Smart Alerts
        </span>
      </div>

      <div className="flex items-center gap-3 ml-auto">
        {streamStatus === 'reconnecting' && (
          <span className="text-xs text-ink bg-line px-2 py-0.5 rounded">
            Reconnecting…
          </span>
        )}
        {streamStatus === 'live' && (
          <span className="text-xs text-ink-muted">● live</span>
        )}

        <ModeBadge mode="LIVE" />

        {ENV !== 'prod' && (
          <span className="text-xs text-ink-muted bg-line px-2 py-0.5 rounded uppercase tracking-wider">
            {ENV}
          </span>
        )}

        <HealthDot />

        <button
          onClick={onToggleMute}
          className="text-ink-muted hover:text-brand transition-colors"
          title={muteAlerts ? 'Unmute audible alerts' : 'Mute audible alerts'}
        >
          {muteAlerts ? <BellOff size={16} /> : <Bell size={16} />}
        </button>

        <span className="text-ink-muted text-sm hidden md:block">Operator</span>
      </div>
    </header>
  )
}
