import type { ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'

interface Props {
  title: string
  subtitle?: string
  onRefresh?: () => void
  refreshing?: boolean
  actions?: ReactNode
}

export function Header({ title, subtitle, onRefresh, refreshing, actions }: Props) {
  return (
    <div
      className="flex items-center justify-between px-6 py-4 border-b shrink-0"
      style={{ borderColor: 'var(--border)' }}
    >
      <div>
        <h1 className="font-semibold text-base" style={{ color: 'var(--text-primary)' }}>
          {title}
        </h1>
        {subtitle && (
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            {subtitle}
          </p>
        )}
      </div>

      {actions ?? (onRefresh && (
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          style={{ background: 'var(--surface-2)', color: 'var(--text-secondary)' }}
        >
          <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      ))}
    </div>
  )
}