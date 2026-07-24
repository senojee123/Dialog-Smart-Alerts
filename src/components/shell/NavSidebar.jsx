import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, AlertTriangle, Map, Camera, Cpu, Users, GitBranch,
  Settings, Monitor, Layers, Bell, Rocket, Palette, PlayCircle,
} from 'lucide-react'

const NAV = [
  // Operations
  { section: 'Operations' },
  { to: '/',            icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/incidents',   icon: AlertTriangle,   label: 'Live Incidents' },
  { to: '/map',         icon: Map,             label: 'Map View' },
  { to: '/road-signs',  icon: Monitor,         label: 'Road Signs' },
  { to: '/devices',     icon: Camera,          label: 'Devices' },
  { to: '/hardware',    icon: Cpu,             label: 'Hardware Units' },

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
    <nav className="w-56 bg-white border-r border-line flex flex-col gap-1.5 py-4 shrink-0 overflow-y-auto shadow-[1px_0_4px_rgba(16,24,40,0.02)]">
      {NAV.map((item, i) => {
        if (item === null) return <div key={i} className="my-2 border-t border-line/60 mx-3" />
        if (item.section) {
          return (
            <div key={i} className="px-4 pt-4 pb-1.5">
              <span className="text-[12px] font-extrabold text-brand uppercase tracking-wider border-b border-brand/20 pb-0.5 inline-block w-full">
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
              `group flex items-center gap-3.5 px-3 py-2.5 text-[13px] font-medium rounded-md mx-3 transition-all relative
               ${isActive
                 ? 'bg-brand/5 text-brand font-semibold'
                 : 'text-ink-muted hover:bg-surface-alt hover:text-ink'}`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-[-12px] top-1/2 -translate-y-1/2 w-[3px] h-6 bg-brand rounded-r" />
                )}
                <item.icon size={16} className={isActive ? 'text-brand' : 'text-ink-subtle group-hover:text-ink transition-colors'} />
                <span>{item.label}</span>
              </>
            )}
          </NavLink>
        )
      })}
    </nav>
  )
}
