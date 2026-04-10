/**
 * TradeoffRadar — 3-axis radar chart: Quality / Speed / Efficiency.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.7
 * Used by: pages/QuantCompare.tsx
 *
 * Normalization:
 *  Quality    → pass_rate * 100 (0~100)
 *  Speed      → decode_tps / max_in_group * 100
 *  Efficiency → inverse battery_delta normalized (lower consumption = higher)
 */
import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  Radar, ResponsiveContainer, Legend, Tooltip,
} from 'recharts'
import type { QuantComparisonGroup } from '@/types'

interface Props {
  group: QuantComparisonGroup
}

const COLORS = ['#6c63ff', '#4caf7d', '#f0a965', '#f06565', '#60a5fa']

export function TradeoffRadar({ group }: Props) {
  const { quants } = group

  if (quants.length === 0) return null

  const maxTps = Math.max(...quants.map((q) => q.performance.avg_decode_tps ?? 0), 1)
  const maxBattery = Math.max(...quants.map((q) => Math.abs(q.resource.avg_battery_delta ?? 0)), 0.01)

  const axes = ['Quality', 'Speed', 'Efficiency']
  const data = axes.map((axis) => {
    const entry: Record<string, string | number> = { axis }
    quants.forEach((q) => {
      let value = 0
      if (axis === 'Quality') {
        value = q.quality.pass_rate * 100
      } else if (axis === 'Speed') {
        value = ((q.performance.avg_decode_tps ?? 0) / maxTps) * 100
      } else {
        const absDelta = Math.abs(q.resource.avg_battery_delta ?? 0)
        value = ((maxBattery - absDelta) / maxBattery) * 100
      }
      entry[q.quant_level] = Math.round(value * 10) / 10
    })
    return entry
  })

  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <h3 className="text-sm font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>
        Trade-off Radar — {group.base_model}
      </h3>
      <p className="text-[10px] mb-4" style={{ color: 'var(--text-secondary)' }}>
        Larger polygon = better overall balance
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
          <PolarGrid stroke="var(--border)" />
          <PolarAngleAxis
            dataKey="axis"
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 100]}
            tick={{ fill: 'var(--text-secondary)', fontSize: 9 }}
            tickCount={5}
          />
          {quants.map((q, i) => (
            <Radar
              key={q.quant_level}
              name={q.quant_level}
              dataKey={q.quant_level}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          ))}
          <Tooltip
            contentStyle={{
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              fontSize: 11,
              color: 'var(--text-primary)',
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}
