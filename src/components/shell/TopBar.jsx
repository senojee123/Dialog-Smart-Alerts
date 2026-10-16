import { useEffect, useRef, useState } from 'react'
import { Bell, BellOff, Menu, PlayCircle, ChevronDown, Radio } from 'lucide-react'
import ModeBadge from './ModeBadge.jsx'
import HealthDot from './HealthDot.jsx'
import dialogLogo from '../../assets/dialog-logo.jpg'
import { useTour, TOUR_OPTIONS } from '../../tour/TourProvider.jsx'

const ENV = import.meta.env.VITE_ENV ?? 'dev'

export default function TopBar({ streamStatus, muteAlerts, onToggleMute, onToggleSidebar }) {
  return (
    <header className="h-16 bg-brand/[0.04] border-b border-line flex items-center px-4 gap-4 shrink-0 z-30">
      <button
        onClick={onToggleSidebar}
        className="text-ink-muted hover:text-ink mr-1 p-1 hover:bg-line/50 rounded transition-colors"
        title="Toggle Sidebar"
      >
        <Menu size={20} />
      </button>
      <div className="flex items-center gap-3.5 min-w-0">
        <img src={dialogLogo} alt="Dialog Logo" className="h-10 w-10 rounded object-contain bg-white border border-line p-1" />
        <span className="text-ink font-bold text-lg tracking-tight hidden sm:block">
          Dialog Smart Alerts
        </span>
      </div>

      <div className="flex items-center gap-3 ml-auto">
        <TourMenu />

        <div data-tour="topbar-status" className="flex items-center gap-3">
        {streamStatus === 'reconnecting' && (
          <span className="text-xs text-ink bg-line px-2 py-0.5 rounded">
            Reconnecting…
          </span>
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
        </div>

        <span className="text-ink-muted text-sm hidden md:block">Operator</span>
      </div>
    </header>
  )
}

function TourMenu() {
  const tour = useTour()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        disabled={tour.active}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border border-brand/30 text-brand bg-white hover:bg-brand-subtle transition-colors disabled:opacity-50"
      >
        <PlayCircle size={14} /> Guided Tour <ChevronDown size={13} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-2 w-72 bg-white border border-line rounded-lg shadow-popover py-1.5 z-toast animate-slide-in">
          {TOUR_OPTIONS.map(opt => {
            const Icon = opt.id === 'live' ? Radio : PlayCircle
            return (
              <button
                key={opt.id}
                role="menuitem"
                onClick={() => { setOpen(false); tour.start(opt.id) }}
                className="w-full flex items-start gap-3 px-3.5 py-2.5 text-left hover:bg-surface-alt transition-colors"
              >
                <Icon size={16} className="text-brand mt-0.5 shrink-0" />
                <span>
                  <span className="block text-[13px] font-semibold text-ink">{opt.label}</span>
                  <span className="block text-[11.5px] text-ink-muted">{opt.hint}</span>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
