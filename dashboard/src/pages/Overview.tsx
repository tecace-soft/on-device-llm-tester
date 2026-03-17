import { Activity, CheckCircle, Clock, Zap } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, Legend,
} from 'recharts'
import { Header } from '@/components/layout/Header'
import { KpiCard } from '@/components/cards/KpiCard'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { KpiSkeleton, ChartSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useSummary, useByModel, useByCategory, useRefresh } from '@/hooks/useResults'

const COLORS = ['#6c63ff', '#4caf7d', '#f0a965', '#f06565', '#60a5fa', '#a78bfa']

function fmt(val: number | null | undefined, decimals = 1, unit = ''): string {
  if (val == null) return '—'
  return `${val.toFixed(decimals)}${unit}`
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs shadow-lg"
      style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
    >
      <p className="font-medium mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: <span className="font-semibold">{typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</span>
        </p>
      ))}
    </div>
  )
}

function LatencyByModel() {
  const { data, loading, error } = useByModel()

  if (loading) return <ChartSkeleton height={280} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No model data" />

  const chartData = data.map((m) => ({
    name: m.model_name.length > 20 ? m.model_name.slice(0, 20) + '…' : m.model_name,
    'Avg Latency (ms)': m.stats.latency?.avg != null ? +m.stats.latency.avg.toFixed(1) : null,
    'p95 (ms)': m.stats.latency?.p95 != null ? +m.stats.latency.p95.toFixed(1) : null,
  }))

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 40 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="name"
          tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
          angle={-25}
          textAnchor="end"
          interval={0}
        />
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="ms" width={60} />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)', paddingTop: 8 }} />
        <Bar dataKey="Avg Latency (ms)" fill={COLORS[0]} radius={[4, 4, 0, 0]} />
        <Bar dataKey="p95 (ms)" fill={COLORS[2]} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function SuccessRateByCategory() {
  const { data, loading, error } = useByCategory()

  if (loading) return <ChartSkeleton height={280} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No category data" />

  const chartData = data.map((c) => ({
    name: c.category,
    'Success Rate (%)': +c.stats.success_rate.toFixed(1),
  }))

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="name" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="%" domain={[0, 100]} width={45} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="Success Rate (%)" radius={[4, 4, 0, 0]}>
          {chartData.map((entry, i) => (
            <Cell
              key={i}
              fill={
                entry['Success Rate (%)'] >= 80
                  ? COLORS[1]
                  : entry['Success Rate (%)'] >= 50
                  ? COLORS[2]
                  : COLORS[3]
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function Overview() {
  const { tick, refresh } = useRefresh()
  const { data: summary, loading, error } = useSummary({})
  void tick

  return (
    <div className="flex flex-col flex-1 overflow-auto">
      <Header title="Overview" subtitle="Overall benchmark summary" onRefresh={refresh} />

      <div className="p-6 flex flex-col gap-6">

        {loading ? (
          <KpiSkeleton />
        ) : error ? (
          <ErrorFallback error={error} />
        ) : (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              title="Total Tests"
              value={summary?.total ?? '—'}
              sub={`${summary?.success ?? 0} success / ${summary?.errors ?? 0} errors`}
              icon={<Activity size={16} />}
              color="var(--accent)"
            />
            <KpiCard
              title="Success Rate"
              value={fmt(summary?.success_rate, 1, '%')}
              sub={`${summary?.success ?? 0} of ${summary?.total ?? 0} passed`}
              icon={<CheckCircle size={16} />}
              color="var(--success)"
            />
            <KpiCard
              title="Avg Latency"
              value={fmt(summary?.latency?.avg, 0, ' ms')}
              sub={`p95: ${fmt(summary?.latency?.p95, 0, ' ms')}`}
              icon={<Clock size={16} />}
              color="var(--warning)"
            />
            <KpiCard
              title="Avg Decode TPS"
              value={fmt(summary?.avg_decode_tps, 1)}
              sub={`Prefill: ${fmt(summary?.avg_prefill_tps, 1)} tps`}
              icon={<Zap size={16} />}
              color="var(--accent)"
            />
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div
            className="rounded-xl p-5"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
              Avg Latency by Model
            </h2>
            <LatencyByModel />
          </div>

          <div
            className="rounded-xl p-5"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
              Success Rate by Category
            </h2>
            <SuccessRateByCategory />
          </div>
        </div>

      </div>
    </div>
  )
}