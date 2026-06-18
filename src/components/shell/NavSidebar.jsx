import { NavLink } from 'react-router-dom'
import { AlertTriangle, Map, Camera, Cpu, Users, GitBranch, Settings, Monitor } from 'lucide-react'

const NAV = [
  { to: '/incidents',  icon: AlertTriangle, label: 'Live Incidents' },
  { to: '/map',        icon: Map,           label: 'Map' },
  { to: '/road-signs', icon: Monitor,    label: 'Road Signs' },
  { to: '/devices',    icon: Camera,        label: 'Devices' },
  { to: '/hardware',   icon: Cpu,           label: 'Hardware Units' },
  null,
  { to: '/admin/stakeholders', icon: Users,      label: 'Stakeholders' },
  { to: '/admin/rules',        icon: GitBranch,  label: 'Rules' },
  { to: '/admin/road-signs',   icon: Monitor, label: 'Sign Boards' },
  { to: '/admin/escalation',   icon: Settings,   label: 'Escalation' },
  { to: '/admin/templates',    icon: Settings,   label: 'Templates' },
]

export default function NavSidebar() {
  return (
    <nav className="w-56 bg-surface border-r border-line flex flex-col py-4 shrink-0 overflow-y-auto">
      {NAV.map((item, i) =>
        item === null ? (
          <div key={i} className="my-3 border-t border-line mx-3" />
        ) : (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2.5 text-sm rounded-md mx-2 transition-colors
               ${isActive
                 ? 'bg-brand/10 text-brand font-semibold'
                 : 'text-ink-muted hover:bg-surface-alt hover:text-ink'}`
            }
          >
            <item.icon size={16} />
            {item.label}
          </NavLink>
        )
      )}
    </nav>
  )
}
