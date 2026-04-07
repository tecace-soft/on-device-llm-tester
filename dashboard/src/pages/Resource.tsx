import { Battery, Thermometer, Zap, HardDrive } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { Header } from '@/components/layout/Header'
import { KpiCard } from '@/components/cards/KpiCard'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { KpiSkeleton, ChartSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useSummary, useByModel, useRefresh } from '@/hooks/useResults'

const COLORS = ['#f06565', '#f0a965', '#6c63ff', '#4caf7d', '#60a5fa', '#a78bfa']

function fmt(val: number | null | undefined, decimals = 1, unit = ''): string {
  if (val == null) return '—'
  return `${val.toFixed(decimals)}${unit}`
}

function fmtSign(val: number | null | undefined, decimals = 1, unit = ''): string {
  if (val == null) return '—'
  const sign = val > 0 ? '+' : ''
  return `${sign}${val.toFixed(decimals)}${unit}`
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

function ThermalByModel() {
  const { data, loading, error } = useByModel()

  if (loading) return <ChartSkeleton height={280} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No model data" />

  const chartData = data
    .filter((m) => m.stats.resource?.avg_thermal_delta_celsius != null)
    .map((m) => ({
      name: m.model_name.length > 20 ? m.model_name.slice(0, 20) + '…' : m.model_name,
      'Thermal Δ (°C)': m.stats.resource?.avg_thermal_delta_celsius != null
        ? +m.stats.resource.avg_thermal_delta_celsius.toFixed(2)
        : null,
    }))

  if (!chartData.length) return <EmptyState message="No resource profiling data yet" description="Run benchmarks with resource_profiler enabled to see thermal data." />

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
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="°C" width={50} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="Thermal Δ (°C)" fill={COLORS[0]} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function VoltageByModel() {
  const { data, loading, error } = useByModel()

  if (loading) return <ChartSkeleton height={280} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No model data" />

  const chartData = data
    .filter((m) => m.stats.resource?.avg_voltage_delta_mv != null)
    .map((m) => ({
      name: m.model_name.length > 20 ? m.model_name.slice(0, 20) + '…' : m.model_name,
      'Voltage Δ (mV)': m.stats.resource?.avg_voltage_delta_mv != null
        ? +m.stats.resource.avg_voltage_delta_mv.toFixed(1)
        : null,
    }))

  if (!chartData.length) return <EmptyState message="No voltage data" />

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
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="mV" width={55} />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="Voltage Δ (mV)" fill={COLORS[1]} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function PssByModel() {
  const { data, loading, error } = useByModel()

  if (loading) return <ChartSkeleton height={280} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No model data" />

  const chartData = data
    .filter((m) => m.stats.resource?.avg_system_pss_mb != null)
    .map((m) => ({
      name: m.model_name.length > 20 ? m.model_name.slice(0, 20) + '…' : m.model_name,
      'System PSS (MB)': m.stats.resource?.avg_system_pss_mb != null
        ? +m.stats.resource.avg_system_pss_mb.toFixed(0)
        : null,
      'Native Mem (MB)': m.stats.avg_peak_native_mem_mb != null
        ? +m.stats.avg_peak_native_mem_mb.toFixed(0)
        : null,
    }))

  if (!chartData.length) return <EmptyState message="No memory data" />

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
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="MB" width={55} />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)', paddingTop: 8 }} />
        <Bar dataKey="System PSS (MB)" fill={COLORS[2]} radius={[4, 4, 0, 0]} />
        <Bar dataKey="Native Mem (MB)" fill={COLORS[3]} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function Resource() {
  const { refresh } = useRefresh()
  const { data: summary, loading, error } = useSummary({})

  const res = summary?.resource

  return (
    <div className="flex flex-col flex-1 overflow-auto">
      <Header title="Resource Profiling" subtitle="Battery, thermal, and memory analysis" onRefresh={refresh} />

      <div className="p-6 flex flex-col gap-6">

        {loading ? (
          <KpiSkeleton />
        ) : error ? (
          <ErrorFallback error={error} />
        ) : !res ? (
          <div
            className="rounded-xl p-6 text-center"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
              No resource profiling data yet. Run benchmarks with Phase 6 resource_profiler to see data here.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              title="Avg Thermal Δ"
              value={fmtSign(res.avg_thermal_delta_celsius, 1, '°C')}
              sub={`Coverage: ${fmt(res.profiling_coverage, 0, '%')}`}
              icon={<Thermometer size={16} />}
              color="var(--danger)"
            />
            <KpiCard
              title="Avg Voltage Δ"
              value={fmtSign(res.avg_voltage_delta_mv, 0, ' mV')}
              sub="Battery voltage drop"
              icon={<Battery size={16} />}
              color="var(--warning)"
            />
            <KpiCard
              title="Avg Current Δ"
              value={fmtSign(res.avg_current_delta_ua, 0, ' μA')}
              sub="Current draw change"
              icon={<Zap size={16} />}
              color="var(--accent)"
            />
            <KpiCard
              title="Avg System PSS"
              value={fmt(res.avg_system_pss_mb, 0, ' MB')}
              sub="Total memory footprint"
              icon={<HardDrive size={16} />}
              color="var(--success)"
            />
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div
            className="rounded-xl p-5"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
              Thermal Impact by Model
            </h2>
            <ThermalByModel />
          </div>

          <div
            className="rounded-xl p-5"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
              Voltage Drop by Model
            </h2>
            <VoltageByModel />
          </div>
        </div>

        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
            Memory: System PSS vs App Native
          </h2>
          <PssByModel />
        </div>

      </div>
    </div>
  )
}