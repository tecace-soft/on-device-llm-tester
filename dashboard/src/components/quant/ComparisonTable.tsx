/**
 * ComparisonTable — side-by-side quant comparison with baseline deltas.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.6
 * Used by: pages/QuantCompare.tsx
 *
 * Delta color rules (§8.6):
 *  - |delta| <= 5%  → grey (negligible)
 *  - positive + higher-is-better (TPS ↑)  → green
 *  - negative + lower-is-better (latency ↓)  → green
 *  - bad direction  → red
 *  - baseline row  → accent-tinted background, no delta shown
 */
import type { QuantComparisonGroup, QuantBaseline } from '@/types'

interface Props {
  group: QuantComparisonGroup
}

function fmt(v: number | null, decimals = 1, suffix = ''): string {
  if (v == null) return '—'
  return `${v.toFixed(decimals)}${suffix}`
}

function DeltaBadge({ value, higherIsBetter }: { value: number | null; higherIsBetter: boolean }) {
  if (value == null) return <span style={{ color: 'var(--text-secondary)' }}>—</span>

  const abs = Math.abs(value)
  const arrow = value > 0 ? '↑' : '↓'
  const sign = value > 0 ? '+' : ''

  if (abs <= 5) {
    return (
      <span className="text-[10px] ml-1.5" style={{ color: 'var(--text-secondary)' }}>
        {arrow} {sign}{value.toFixed(1)}%
      </span>
    )
  }

  const isGood = higherIsBetter ? value > 0 : value < 0
  const color = isGood ? 'var(--success)' : 'var(--error)'

  return (
    <span className="text-[10px] font-medium ml-1.5" style={{ color }}>
      {arrow} {sign}{value.toFixed(1)}%
    </span>
  )
}

const HEADERS = ['Quant', 'Count', 'Decode TPS', 'Latency (ms)', 'TTFT (ms)', 'Pass Rate', 'Battery Δ', 'Thermal Δ', 'PSS (MB)']

export function ComparisonTable({ group }: Props) {
  const { quants, deltas } = group

  const deltaMap = new Map<string, QuantBaseline>()
  deltas.forEach((d) => deltaMap.set(d.quant_level, d))

  // Baseline = quant not present in deltas
  const deltaQuants = new Set(deltas.map((d) => d.quant_level))
  const baselineLevel = quants.find((q) => !deltaQuants.has(q.quant_level))?.quant_level ?? ''

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div className="px-5 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Quantization Comparison — {group.base_model}
        </h3>
        <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-secondary)' }}>
          Baseline: {baselineLevel} (highest precision)
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {HEADERS.map((h) => (
                <th
                  key={h}
                  className="px-4 py-2.5 text-left font-medium whitespace-nowrap"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {quants.map((q) => {
              const isBaseline = q.quant_level === baselineLevel
              const d = deltaMap.get(q.quant_level)
              const bg = isBaseline ? 'rgba(108,99,255,0.06)' : 'transparent'

              return (
                <tr
                  key={q.quant_level}
                  style={{ background: bg, borderBottom: '1px solid var(--border)' }}
                >
                  <td className="px-4 py-2.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>
                    {q.quant_level}
                    {isBaseline && (
                      <span
                        className="ml-1.5 text-[9px] px-1.5 py-0.5 rounded"
                        style={{ background: 'var(--accent)', color: '#fff' }}
                      >
                        baseline
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-secondary)' }}>
                    {q.result_count}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.performance.avg_decode_tps)}
                    {!isBaseline && <DeltaBadge value={d?.tps_change_pct ?? null} higherIsBetter={true} />}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.performance.avg_latency_ms, 0)}
                    {!isBaseline && <DeltaBadge value={d?.latency_change_pct ?? null} higherIsBetter={false} />}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.performance.avg_ttft_ms, 0)}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.quality.pass_rate * 100, 1, '%')}
                    {!isBaseline && <DeltaBadge value={d?.pass_rate_change_pct ?? null} higherIsBetter={true} />}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.resource.avg_battery_delta, 2, '%')}
                    {!isBaseline && <DeltaBadge value={d?.battery_change_pct ?? null} higherIsBetter={false} />}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.resource.avg_thermal_delta_celsius, 1, '°C')}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: 'var(--text-primary)' }}>
                    {fmt(q.resource.avg_system_pss_mb, 0)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
