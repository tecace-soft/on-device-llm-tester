/**
 * InsightCards — renders auto-generated insight strings from each QuantComparisonGroup.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.2
 * Used by: pages/QuantCompare.tsx
 */
import { Lightbulb } from 'lucide-react'
import type { QuantComparisonGroup } from '@/types'

interface Props {
  groups: QuantComparisonGroup[]
}

export function InsightCards({ groups }: Props) {
  if (groups.length === 0) return null

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {groups.map((g) => (
        <div
          key={g.base_model}
          className="flex items-start gap-3 rounded-xl px-5 py-4"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <div
            className="flex items-center justify-center w-9 h-9 rounded-lg shrink-0 mt-0.5"
            style={{ background: 'rgba(108,99,255,0.15)' }}
          >
            <Lightbulb size={16} style={{ color: 'var(--accent)' }} />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
              {g.base_model}
            </p>
            <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>
              {g.insight}
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}
