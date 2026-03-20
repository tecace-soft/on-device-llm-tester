import { NavLink } from 'react-router-dom'
import { LayoutDashboard, TrendingUp, GitCompare, MessageSquare, Table2, Cpu, History, Smartphone } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/performance', label: 'Performance', icon: TrendingUp },
  { to: '/compare', label: 'Compare', icon: GitCompare },
  { to: '/device-compare', label: 'Device Compare', icon: Smartphone },
  { to: '/responses', label: 'Responses', icon: MessageSquare },
  { to: '/raw', label: 'Raw Data', icon: Table2 },
  { to: '/runs', label: 'Run History', icon: History },
]

export function Sidebar() {
  return (
    <aside
      className="flex flex-col w-56 min-h-screen shrink-0 border-r"
      style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-5 border-b" style={{ borderColor: 'var(--border)' }}>
        <Cpu size={20} style={{ color: 'var(--accent)' }} />
        <span className="font-semibold text-sm tracking-wide" style={{ color: 'var(--text-primary)' }}>
          LLM Tester
        </span>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-1 px-3 py-4 flex-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive ? 'active-nav' : 'inactive-nav'
              }`
            }
            style={({ isActive }) => ({
              background: isActive ? 'var(--accent)' : 'transparent',
              color: isActive ? '#fff' : 'var(--text-secondary)',
            })}
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t text-xs" style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}>
        v3.0.0 · multi-device
      </div>
    </aside>
  )
}