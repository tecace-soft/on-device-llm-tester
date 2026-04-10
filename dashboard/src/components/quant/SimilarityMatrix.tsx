/**
 * SimilarityMatrix — N×N heatmap of pairwise quant response similarity.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.8
 * Used by: pages/QuantCompare.tsx
 *
 * Color scheme:
 *  0.8+    → deep green (nearly identical)
 *  0.6~0.8 → light green (similar)
 *  0.4~0.6 → yellow (different)
 *  <0.4    → red (very different)
 */
import { useMemo } from 'react'
import type { QuantSimilarityResponse } from '@/types'

interface Props {
  similarity: QuantSimilarityResponse
}

function ratioColor(ratio: number): string {
  if (ratio >= 0.8) return 'rgba(76,175,125,0.6)'
  if (ratio >= 0.6) return 'rgba(76,175,125,0.3)'
  if (ratio >= 0.4) return 'rgba(240,169,101,0.4)'
  return 'rgba(240,101,101,0.4)'
}

export function SimilarityMatrix({ similarity }: Props) {
  const { pairs } = similarity

  const matrix = useMemo(() => {
    const quantSet = new Set<string>()
    pairs.forEach((p) => {
      quantSet.add(p.quant_a)
      quantSet.add(p.quant_b)
    })
    const quants = Array.from(quantSet).sort()

    // Aggregate average match_ratio per quant pair
    const pairMap = new Map<string, { total: number; count: number }>()
    pairs.forEach((p) => {
      // Store both directions for symmetric lookup
      for (const k of [`${p.quant_a}|${p.quant_b}`, `${p.quant_b}|${p.quant_a}`]) {
        const existing = pairMap.get(k) ?? { total: 0, count: 0 }
        existing.total += p.match_ratio
        existing.count += 1
        pairMap.set(k, existing)
      }
    })

    const getAvg = (a: string, b: string): number | null => {
      if (a === b) return null
      const entry = pairMap.get(`${a}|${b}`)
      if (!entry || entry.count === 0) return null
      return entry.total / entry.count
    }

    return { quants, getAvg }
  }, [pairs])

  if (matrix.quants.length < 2) return null

  const { quants, getAvg } = matrix

  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <h3 className="text-sm font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>
        Response Similarity Matrix
      </h3>
      <p className="text-[10px] mb-4" style={{ color: 'var(--text-secondary)' }}>
        Average SequenceMatcher ratio across all prompts · Overall: {(similarity.overall_avg_ratio * 100).toFixed(1)}%
      </p>

      <div
        className="inline-grid gap-1"
        style={{
          gridTemplateColumns: `auto ${quants.map(() => '64px').join(' ')}`,
        }}
      >
        {/* Header row */}
        <div />
        {quants.map((q) => (
          <div
            key={`h-${q}`}
            className="text-[10px] font-medium text-center py-1"
            style={{ color: 'var(--text-secondary)' }}
          >
            {q}
          </div>
        ))}

        {/* Data rows */}
        {quants.map((rowQ) => (
          <div key={`row-${rowQ}`} className="contents">
            <div
              className="text-[10px] font-medium flex items-center pr-2"
              style={{ color: 'var(--text-secondary)' }}
            >
              {rowQ}
            </div>
            {quants.map((colQ) => {
              const avg = getAvg(rowQ, colQ)
              const isDiag = rowQ === colQ

              return (
                <div
                  key={`${rowQ}-${colQ}`}
                  className="flex items-center justify-center rounded text-[10px] font-medium h-10"
                  style={{
                    background: isDiag ? 'var(--surface-2)' : avg != null ? ratioColor(avg) : 'var(--surface-2)',
                    color: isDiag ? 'var(--text-secondary)' : 'var(--text-primary)',
                  }}
                >
                  {isDiag ? '—' : avg != null ? (avg * 100).toFixed(1) + '%' : '—'}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
