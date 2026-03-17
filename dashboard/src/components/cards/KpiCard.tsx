import type { ReactNode } from 'react'

interface Props {
  title: string
  value: string | number
  sub?: string
  icon?: ReactNode
  color?: string
}

export function KpiCard({ title, value, sub, icon, color = 'var(--accent)' }: Props) {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
          {title}
        </span>
        {icon && (
          <span className="flex items-center justify-center w-8 h-8 rounded-lg" style={{ background: 'var(--surface-2)', color }}>
            {icon}
          </span>
        )}
      </div>
      <div>
        <p className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
          {value}
        </p>
        {sub && (
          <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
            {sub}
          </p>
        )}
      </div>
    </div>
  )
}