/**
 * CategorySimilarity — horizontal bar chart of per-category average similarity.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.2 (Category Similarity Breakdown)
 * Used by: pages/QuantCompare.tsx
 */
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts'
import type { QuantSimilaritySummary } from '@/types'

interface Props {
  byCategory: QuantSimilaritySummary[]
  overallAvg: number
}

function barColor(ratio: number): string {
  if (ratio >= 0.8) return '#4caf7d'
  if (ratio >= 0.6) return '#f0a965'
  return '#f06565'
}

export function CategorySimilarity({ byCategory, overallAvg }: Props) {
  if (byCategory.length === 0) return null

  const data = byCategory.map((c) => ({
    category: c.category,
    similarity: Math.round(c.avg_match_ratio * 1000) / 10,
    pairs: c.pair_count,
  }))

  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <h3 className="text-sm font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>
        Category Similarity Breakdown
      </h3>
      <p className="text-[10px] mb-4" style={{ color: 'var(--text-secondary)' }}>
        Average cross-quant response similarity per category · Overall avg: {(overallAvg * 100).toFixed(1)}%
      </p>

      <ResponsiveContainer width="100%" height={Math.max(180, byCategory.length * 36 + 40)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, 100]}
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            tickFormatter={(v) => `${v}%`}
          />
          <YAxis
            type="category"
            dataKey="category"
            width={90}
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              fontSize: 11,
              color: 'var(--text-primary)',
            }}
            formatter={(value, _name, entry: any) => [
              `${Number(value).toFixed(1)}% (${entry.payload.pairs} pairs)`,
              'Similarity',
            ]}
          />
          <ReferenceLine
            x={overallAvg * 100}
            stroke="var(--text-secondary)"
            strokeDasharray="4 4"
            strokeWidth={1}
          />
          <Bar dataKey="similarity" radius={[0, 4, 4, 0]} barSize={20}>
            {data.map((d, i) => (
              <Cell key={i} fill={barColor(d.similarity / 100)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
