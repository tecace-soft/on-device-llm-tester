import type { ValidationStatus } from '@/types'

const STATUS_STYLES: Record<ValidationStatus, { bg: string; color: string; label: string }> = {
  pass:      { bg: 'rgba(76,175,125,0.15)',  color: 'var(--success)',        label: 'Pass' },
  fail:      { bg: 'rgba(240,101,101,0.15)', color: 'var(--error)',          label: 'Fail' },
  warn:      { bg: 'rgba(240,169,101,0.15)', color: 'var(--warning)',        label: 'Warn' },
  uncertain: { bg: 'rgba(139,144,176,0.15)', color: 'var(--text-secondary)', label: 'Uncertain' },
  skip:      { bg: 'rgba(139,144,176,0.08)', color: 'var(--text-secondary)', label: 'Skip' },
}

interface StatusBadgeProps {
  status: ValidationStatus
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.skip
  const cls = size === 'md' ? 'text-xs px-2.5 py-1' : 'text-[10px] px-2 py-0.5'

  return (
    <span
      className={`${cls} rounded-full font-medium whitespace-nowrap`}
      style={{ background: style.bg, color: style.color }}
    >
      {style.label}
    </span>
  )
}