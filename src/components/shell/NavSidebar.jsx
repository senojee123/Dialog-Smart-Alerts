import { NavLink } from 'react-router-dom'
import {
  AlertTriangle, Map, Camera, Cpu, Users, GitBranch,
  Settings, Monitor, Layers, Bell, Rocket, Palette, PlayCircle,
} from 'lucide-react'

const NAV = [
  // Operations
  { section: 'Operations' },
  { to: '/incidents',   icon: AlertTriangle, label: 'Live Incidents' },
  { to: '/map',         icon: Map,           label: 'Map View' },
  { to: '/road-signs',  icon: Monitor,       label: 'Road Signs' },
  { to: '/devices',     icon: Camera,        label: 'Devices' },
  { to: '/hardware',    icon: Cpu,           label: 'Hardware Units' },
  { to: '/simulator',   icon: PlayCircle,    label: 'Simulator' },

  null, // divider

  // Configuration
  { section: 'Configuration' },
  { to: '/setup',             icon: Rocket,        label: 'Setup Wizard' },
  { to: '/admin/use-cases',   icon: Layers,        label: 'Use Cases' },
  { to: '/admin/rules',       icon: GitBranch,     label: 'Rules Engine' },
  { to: '/admin/stakeholders',icon: Users,         label: 'Stakeholders' },
  { to: '/admin/devices',     icon: Camera,        label: 'Device Registry' },
  { to: '/admin/road-signs',  icon: Monitor,       label: 'Sign Board Registry' },

  null, // divider

  // System
  { section: 'System' },
  { to: '/admin/escalation',  icon: Bell,     label: 'Escalation' },
  { to: '/admin/templates',   icon: Settings, label: 'Templates' },
  { to: '/styleguide',        icon: Palette,  label: 'Design System' },
]

export default function NavSidebar() {
  return (
    <nav className="w-52 bg-white border-r border-line flex flex-col py-3 shrink-0 overflow-y-auto shadow-[1px_0_4px_rgba(16,24,40,0.02)]">
      {NAV.map((item, i) => {
        if (item === null) return <div key={i} className="my-2 border-t border-line/60 mx-3" />
        if (item.section) {
          const isOperations = item.section === 'Operations'
          return (
            <div key={i} className="px-4 pt-4 pb-1">
              <span className={isOperations
                ? "text-[12px] font-extrabold text-brand uppercase tracking-wider border-b border-brand/20 pb-0.5 inline-block w-full"
                : "text-[10px] font-bold text-ink-muted/50 uppercase tracking-wider"
              }>
                {item.section}
              </span>
            </div>
          )
        }
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `group flex items-center gap-3 px-3 py-1.5 text-xs font-medium rounded-md mx-2 transition-all relative
               ${isActive
                 ? 'bg-brand/5 text-brand font-semibold'
                 : 'text-ink-muted hover:bg-surface-alt hover:text-ink'}`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-[-8px] top-1/2 -translate-y-1/2 w-[3px] h-5 bg-brand rounded-r" />
                )}
                <item.icon size={14} className={isActive ? 'text-brand' : 'text-ink-subtle group-hover:text-ink transition-colors'} />
                <span>{item.label}</span>
              </>
            )}
          </NavLink>
        )
      })}
    </nav>
  )
}
