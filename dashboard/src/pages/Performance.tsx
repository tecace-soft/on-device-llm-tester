import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine,
  ComposedChart, Cell,
} from 'recharts'
import { Header } from '@/components/layout/Header'
import { FilterBar } from '@/components/filters/FilterBar'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ChartSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useResults, useByModel, useByCategory, useRefresh } from '@/hooks/useResults'
import { useFilters } from '@/hooks/useFilters'
import type { ResultItem, ResultSuccess } from '@/types'

const COLORS = ['#6c63ff', '#4caf7d', '#f0a965', '#f06565', '#60a5fa', '#a78bfa']

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
    >
      <p className="font-medium mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color ?? 'var(--text-primary)' }}>
          {p.name}: <span className="font-semibold">{typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</span>
        </p>
      ))}
    </div>
  )
}

// ── Latency Distribution Histogram ─────────────────────────────────────────────
function LatencyHistogram({ items }: { items: ResultItem[] }) {
  const successItems = items.filter((r): r is ResultSuccess => r.status === 'success')
  if (!successItems.length) return <EmptyState message="No latency data" />

  const latencies = successItems.map((r) => r.latency_ms).filter((v): v is number => v != null)
  const min = Math.min(...latencies)
  const max = Math.max(...latencies)
  const bucketCount = Math.min(20, Math.ceil(Math.sqrt(latencies.length)))
  const bucketSize = (max - min) / bucketCount || 1

  const buckets: { range: string; count: number; mid: number }[] = Array.from(
    { length: bucketCount },
    (_, i) => ({
      range: `${Math.round(min + i * bucketSize)}`,
      mid: min + (i + 0.5) * bucketSize,
      count: 0,
    }),
  )
  latencies.forEach((v) => {
    const idx = Math.min(Math.floor((v - min) / bucketSize), bucketCount - 1)
    buckets[idx].count++
  })

  const sorted = [...latencies].sort((a, b) => a - b)
  const pct = (p: number) => sorted[Math.floor((p / 100) * (sorted.length - 1))]
  const p50 = pct(50), p95 = pct(95), p99 = pct(99)

  return (
    <div>
      <div className="flex gap-4 mb-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
        <span>p50: <strong style={{ color: COLORS[1] }}>{p50.toFixed(0)}ms</strong></span>
        <span>p95: <strong style={{ color: COLORS[2] }}>{p95.toFixed(0)}ms</strong></span>
        <span>p99: <strong style={{ color: COLORS[3] }}>{p99.toFixed(0)}ms</strong></span>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={buckets} margin={{ top: 4, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="range" tick={{ fill: 'var(--text-secondary)', fontSize: 10 }} unit="ms" />
          <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} allowDecimals={false} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="count" fill={COLORS[0]} radius={[3, 3, 0, 0]} name="Count" />
          <ReferenceLine x={buckets.reduce((best, b) => Math.abs(b.mid - p50) < Math.abs(best.mid - p50) ? b : best).range} stroke={COLORS[1]} strokeDasharray="4 2" label={{ value: 'p50', fill: COLORS[1], fontSize: 10 }} />
          <ReferenceLine x={buckets.reduce((best, b) => Math.abs(b.mid - p95) < Math.abs(best.mid - p95) ? b : best).range} stroke={COLORS[2]} strokeDasharray="4 2" label={{ value: 'p95', fill: COLORS[2], fontSize: 10 }} />
          <ReferenceLine x={buckets.reduce((best, b) => Math.abs(b.mid - p99) < Math.abs(best.mid - p99) ? b : best).range} stroke={COLORS[3]} strokeDasharray="4 2" label={{ value: 'p99', fill: COLORS[3], fontSize: 10 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Decode TPS by Category (grouped by model) ──────────────────────────────────
function TpsByCategory({ filters }: { filters: { device?: string; backend?: string } }) {
  const { data: byModel, loading, error } = useByModel(filters)
  const { data: byCat } = useByCategory(filters)

  if (loading) return <ChartSkeleton height={260} />
  if (error) return <ErrorFallback error={error} />
  if (!byModel?.length) return <EmptyState message="No TPS data" />

  const categories = byCat?.map((c) => c.category) ?? []
  const modelNames = byModel.map((m) => m.model_name.slice(0, 18))

  const chartData = categories.map((cat) => {
    const row: Record<string, any> = { category: cat }
    byModel.forEach((m) => {
      row[m.model_name.slice(0, 18)] = m.stats.avg_decode_tps != null
        ? +m.stats.avg_decode_tps.toFixed(1)
        : null
    })
    return row
  })

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="category" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit=" tps" width={55} />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }} />
        {modelNames.map((name, i) => (
          <Bar key={name} dataKey={name} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── TTFT by Model ──────────────────────────────────────────────────────────────
function TtftByModel({ filters }: { filters: { device?: string; backend?: string } }) {
  const { data: byModel, loading, error } = useByModel(filters)

  if (loading) return <ChartSkeleton height={260} />
  if (error) return <ErrorFallback error={error} />
  if (!byModel?.length) return <EmptyState message="No TTFT data" />

  const chartData = byModel
    .filter((m) => m.stats.avg_ttft_ms != null)
    .map((m) => ({
      name: m.model_name.length > 20 ? m.model_name.slice(0, 20) + '…' : m.model_name,
      'TTFT (ms)': +(m.stats.avg_ttft_ms!.toFixed(1)),
    }))

  if (!chartData.length) return <EmptyState message="No TTFT data" />

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 40 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="name" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} angle={-25} textAnchor="end" interval={0} />
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="ms" width={60} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="TTFT (ms)" radius={[4, 4, 0, 0]}>
          {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── Memory Footprint by Model ──────────────────────────────────────────────────
function MemoryByModel({ filters }: { filters: { device?: string; backend?: string } }) {
  const { data: byModel, loading, error } = useByModel(filters)

  if (loading) return <ChartSkeleton height={260} />
  if (error) return <ErrorFallback error={error} />
  if (!byModel?.length) return <EmptyState message="No memory data" />

  const chartData = byModel
    .filter((m) => m.stats.avg_peak_native_mem_mb != null || m.stats.avg_peak_java_mem_mb != null)
    .map((m) => ({
      name: m.model_name.length > 20 ? m.model_name.slice(0, 20) + '…' : m.model_name,
      'Native (MB)': m.stats.avg_peak_native_mem_mb != null ? +(m.stats.avg_peak_native_mem_mb.toFixed(1)) : null,
      'Java (MB)': m.stats.avg_peak_java_mem_mb != null ? +(m.stats.avg_peak_java_mem_mb.toFixed(1)) : null,
    }))

  if (!chartData.length) return <EmptyState message="No memory data" />

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 40 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="name" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} angle={-25} textAnchor="end" interval={0} />
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="MB" width={60} />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }} />
        <Bar dataKey="Native (MB)" fill={COLORS[0]} radius={[3, 3, 0, 0]} />
        <Bar dataKey="Java (MB)" fill={COLORS[1]} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── Chart Card wrapper ─────────────────────────────────────────────────────────
function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
        {title}
      </h2>
      {children}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function Performance() {
  const { filters, setFilter, resetFilters } = useFilters()
  const { refresh } = useRefresh()

  const { data: results, loading, error } = useResults({ ...filters, limit: 500, offset: 0 })
  const items = results?.items ?? []

  const chartFilters = { device: filters.device, backend: filters.backend }

  return (
    <div className="flex flex-col flex-1 overflow-auto">
      <Header title="Performance" subtitle="Latency, TPS, TTFT & memory analysis" onRefresh={refresh} />
      <FilterBar filters={filters} onFilter={setFilter} onReset={resetFilters} />

      <div className="p-6 grid grid-cols-1 gap-6 lg:grid-cols-2">

        <ChartCard title="Latency Distribution">
          {loading ? <ChartSkeleton height={260} /> : error ? <ErrorFallback error={error} /> : <LatencyHistogram items={items} />}
        </ChartCard>

        <ChartCard title="Decode TPS by Category">
          <TpsByCategory filters={chartFilters} />
        </ChartCard>

        <ChartCard title="TTFT by Model">
          <TtftByModel filters={chartFilters} />
        </ChartCard>

        <ChartCard title="Memory Footprint by Model">
          <MemoryByModel filters={chartFilters} />
        </ChartCard>

      </div>
    </div>
  )
}