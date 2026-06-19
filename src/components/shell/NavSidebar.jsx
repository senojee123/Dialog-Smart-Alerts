import { NavLink } from 'react-router-dom'
import {
  AlertTriangle, Map, Camera, Cpu, Users, GitBranch,
  Settings, Monitor, Layers, Bell, Rocket,
} from 'lucide-react'

const NAV = [
  // Operations
  { section: 'Operations' },
  { to: '/incidents',   icon: AlertTriangle, label: 'Live Incidents' },
  { to: '/map',         icon: Map,           label: 'Map' },
  { to: '/road-signs',  icon: Monitor,       label: 'Road Signs' },
  { to: '/devices',     icon: Camera,        label: 'Devices' },
  { to: '/hardware',    icon: Cpu,           label: 'Hardware Units' },

  null, // divider

  // Configuration
  { section: 'Configuration' },
  { to: '/setup',             icon: Rocket,        label: 'Setup Wizard' },
  { to: '/admin/use-cases',   icon: Layers,        label: 'Use Cases' },
  { to: '/admin/rules',       icon: GitBranch,     label: 'Rules Engine' },
  { to: '/admin/stakeholders',icon: Users,         label: 'Stakeholders' },
  { to: '/admin/devices',     icon: Camera,        label: 'Devices' },
  { to: '/admin/road-signs',  icon: Monitor,       label: 'Sign Boards' },

  null, // divider

  // System
  { section: 'System' },
  { to: '/admin/escalation',  icon: Bell,     label: 'Escalation' },
  { to: '/admin/templates',   icon: Settings, label: 'Templates' },
]

export default function NavSidebar() {
  return (
    <nav className="w-56 bg-surface border-r border-line flex flex-col py-2 shrink-0 overflow-y-auto">
      {NAV.map((item, i) => {
        if (item === null) return <div key={i} className="my-2 border-t border-line mx-3" />
        if (item.section) return (
          <div key={i} className="px-4 pt-3 pb-1">
            <span className="text-xs font-semibold text-ink-muted/70 uppercase tracking-widest">{item.section}</span>
          </div>
        )
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2 text-sm rounded-md mx-2 transition-colors
               ${isActive
                 ? 'bg-brand/10 text-brand font-semibold'
                 : 'text-ink-muted hover:bg-surface-alt hover:text-ink'}`
            }
          >
            <item.icon size={15} />
            {item.label}
          </NavLink>
        )
      })}
    </nav>
  )
}
