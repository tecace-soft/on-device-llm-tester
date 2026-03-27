import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ChartSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useValidationByCategory } from '@/hooks/useValidation'

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
          {p.name}: <span className="font-semibold">{p.value}</span>
        </p>
      ))}
    </div>
  )
}

interface Props {
  filters?: { device?: string; model?: string }
}

export function CategoryValidationChart({ filters }: Props) {
  const { data, loading, error } = useValidationByCategory(filters)

  if (loading) return <ChartSkeleton height={300} />
  if (error) return <ErrorFallback error={error} />
  if (!data?.length) return <EmptyState message="No validation data by category" />

  const chartData = data.map((c) => ({
    category: c.category,
    Pass: c.pass_count,
    Fail: c.fail_count,
    Warn: c.warn_count,
    Uncertain: c.uncertain_count,
  }))

  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
        Validation by Category
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis
            dataKey="category"
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
            angle={-30}
            textAnchor="end"
            height={60}
          />
          <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} width={35} />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }} />
          <Bar dataKey="Pass" stackId="a" fill="#4caf7d" radius={[0, 0, 0, 0]} />
          <Bar dataKey="Fail" stackId="a" fill="#f06565" />
          <Bar dataKey="Warn" stackId="a" fill="#f0a965" />
          <Bar dataKey="Uncertain" stackId="a" fill="#8b90b0" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}