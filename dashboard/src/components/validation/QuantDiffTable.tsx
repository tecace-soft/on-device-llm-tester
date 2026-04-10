/**
 * QuantDiffTable — prompt-level response similarity across all model pairs.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8 (Step 8)
 * Depends on: useQuantDiff (hooks/useValidation.ts)
 * Used by: pages/Validation.tsx
 *
 * Unlike QuantCompare page (same base model only), this shows ALL model pair diffs
 * from GET /api/validation/quant-diff.
 */
import { useMemo, useState } from 'react'
import { useQuantDiff } from '@/hooks/useValidation'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'

function ratioColor(ratio: number): string {
  if (ratio >= 0.8) return '#4caf7d'
  if (ratio >= 0.6) return '#8bc34a'
  if (ratio >= 0.4) return '#f0a965'
  return '#f06565'
}

function RatioBadge({ ratio }: { ratio: number }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold"
      style={{ background: `${ratioColor(ratio)}20`, color: ratioColor(ratio) }}
    >
      {(ratio * 100).toFixed(1)}%
    </span>
  )
}

type SortKey = 'match_ratio' | 'category' | 'prompt_text'
type SortDir = 'asc' | 'desc'

export function QuantDiffTable({ filters }: { filters: { device?: string } }) {
  const { data, loading, error } = useQuantDiff(filters)
  const [sortKey, setSortKey] = useState<SortKey>('match_ratio')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [catFilter, setCatFilter] = useState<string>('')

  const categories = useMemo(() => {
    if (!data) return []
    return [...new Set(data.map((d) => d.category))].sort()
  }, [data])

  const sorted = useMemo(() => {
    if (!data) return []
    const items = catFilter ? data.filter((d) => d.category === catFilter) : [...data]
    items.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'match_ratio') cmp = a.match_ratio - b.match_ratio
      else if (sortKey === 'category') cmp = a.category.localeCompare(b.category)
      else cmp = a.prompt_text.localeCompare(b.prompt_text)
      return sortDir === 'asc' ? cmp : -cmp
    })
    return items
  }, [data, sortKey, sortDir, catFilter])

  const avgRatio = useMemo(() => {
    if (!data || data.length === 0) return null
    return data.reduce((sum, d) => sum + d.match_ratio, 0) / data.length
  }, [data])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('asc') }
  }

  const sortIcon = (key: SortKey) => {
    if (sortKey !== key) return ' ↕'
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  if (loading) return <LoadingSkeleton rows={4} />
  if (error) return null
  if (!data || data.length === 0) return null

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Response Similarity (All Model Pairs)
          </h3>
          {avgRatio !== null && (
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
              Overall avg: <span style={{ color: ratioColor(avgRatio), fontWeight: 600 }}>{(avgRatio * 100).toFixed(1)}%</span>
              {' · '}{data.length} pair{data.length !== 1 ? 's' : ''}
            </p>
          )}
        </div>
        <select
          value={catFilter}
          onChange={(e) => setCatFilter(e.target.value)}
          className="px-2 py-1 rounded text-xs"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All Categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs" style={{ color: 'var(--text-primary)' }}>
          <thead>
            <tr style={{ background: 'var(--surface-2)' }}>
              <th
                className="text-left px-4 py-2 font-medium cursor-pointer select-none"
                style={{ color: 'var(--text-secondary)' }}
                onClick={() => toggleSort('category')}
              >
                Category{sortIcon('category')}
              </th>
              <th
                className="text-left px-4 py-2 font-medium cursor-pointer select-none"
                style={{ color: 'var(--text-secondary)' }}
                onClick={() => toggleSort('prompt_text')}
              >
                Prompt{sortIcon('prompt_text')}
              </th>
              <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>
                Model A
              </th>
              <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>
                Model B
              </th>
              <th
                className="text-right px-4 py-2 font-medium cursor-pointer select-none"
                style={{ color: 'var(--text-secondary)' }}
                onClick={() => toggleSort('match_ratio')}
              >
                Match{sortIcon('match_ratio')}
              </th>
              <th className="text-right px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>
                Len A
              </th>
              <th className="text-right px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>
                Len B
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={`${row.prompt_id}-${row.model_a}-${row.model_b}`}
                className="border-t"
                style={{
                  borderColor: 'var(--border)',
                  background: i % 2 === 0 ? 'transparent' : 'var(--surface-2)',
                }}
              >
                <td className="px-4 py-2">
                  <span
                    className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium"
                    style={{ background: 'var(--accent-muted, var(--surface-2))', color: 'var(--text-secondary)' }}
                  >
                    {row.category}
                  </span>
                </td>
                <td className="px-4 py-2 max-w-[280px] truncate" title={row.prompt_text}>
                  {row.prompt_text}
                </td>
                <td className="px-4 py-2 font-mono text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                  {row.model_a}
                </td>
                <td className="px-4 py-2 font-mono text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                  {row.model_b}
                </td>
                <td className="px-4 py-2 text-right">
                  <RatioBadge ratio={row.match_ratio} />
                </td>
                <td className="px-4 py-2 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>
                  {row.a_length.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>
                  {row.b_length.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}