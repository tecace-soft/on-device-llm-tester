import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ChartSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useValidationByModel } from '@/hooks/useValidation'

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
          {p.name}: <span className="font-semibold">{(p.value * 100).toFixed(1)}%</span>
        </p>
      ))}
    </div>
  )
}

interface Props {
  filters?: { device?: string }
}

export function ModelValidationChart({ filters }: Props) {
  const { data, loading, error } = useValidationByModel(filters)

  if (loading) return <ChartSkeleton height={250} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No validation data by model" />

  const chartData = data.map((m) => ({
    model: m.model_name.length > 25 ? m.model_name.slice(0, 22) + '...' : m.model_name,
    'Pass Rate': m.pass_rate,
    'Fail Rate': m.fail_rate,
    'Truncation Rate': m.truncation_rate,
    total: m.total,
  }))

  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
        Validation by Model
      </h3>
      <ResponsiveContainer width="100%" height={Math.max(200, chartData.length * 60)}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis
            type="number"
            domain={[0, 1]}
            tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
          />
          <YAxis
            type="category"
            dataKey="model"
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
            width={160}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }} />
          <Bar dataKey="Pass Rate" fill="#4caf7d" radius={[0, 3, 3, 0]} barSize={16} />
          <Bar dataKey="Fail Rate" fill="#f06565" radius={[0, 3, 3, 0]} barSize={16} />
          <Bar dataKey="Truncation Rate" fill="#f0a965" radius={[0, 3, 3, 0]} barSize={16} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}