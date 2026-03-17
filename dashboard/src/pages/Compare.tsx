import { useState } from 'react'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend,
} from 'recharts'
import { Header } from '@/components/layout/Header'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ChartSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useModels, useCompare, useRefresh } from '@/hooks/useResults'
import type { CompareResult } from '@/types'

const COLOR_A = '#6c63ff'
const COLOR_B = '#4caf7d'

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

// ── Stat row ───────────────────────────────────────────────────────────────────
function StatRow({ label, a, b, unit = '', higherIsBetter = false }: {
  label: string
  a: number | null | undefined
  b: number | null | undefined
  unit?: string
  higherIsBetter?: boolean
}) {
  const fmt = (v: number | null | undefined) => v != null ? `${v.toFixed(1)}${unit}` : '—'
  const winner = a != null && b != null
    ? higherIsBetter ? (a > b ? 'a' : a < b ? 'b' : 'tie') : (a < b ? 'a' : a > b ? 'b' : 'tie')
    : null

  return (
    <div className="grid grid-cols-3 items-center py-2 border-b text-sm" style={{ borderColor: 'var(--border)' }}>
      <span style={{ color: winner === 'a' ? COLOR_A : 'var(--text-primary)', fontWeight: winner === 'a' ? 600 : 400 }}>{fmt(a)}</span>
      <span className="text-center text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span className="text-right" style={{ color: winner === 'b' ? COLOR_B : 'var(--text-primary)', fontWeight: winner === 'b' ? 600 : 400 }}>{fmt(b)}</span>
    </div>
  )
}

// ── Radar chart ────────────────────────────────────────────────────────────────
function CategoryRadar({ results }: { results: CompareResult[] }) {
  if (results.length < 2) return null

  const [a, b] = results
  const allCats = Array.from(new Set([
    ...a.by_category.map((c) => c.category),
    ...b.by_category.map((c) => c.category),
  ]))

  const chartData = allCats.map((cat) => {
    const ca = a.by_category.find((c) => c.category === cat)
    const cb = b.by_category.find((c) => c.category === cat)
    return {
      category: cat,
      [a.model_name.slice(0, 14)]: ca?.stats.avg_decode_tps ?? 0,
      [b.model_name.slice(0, 14)]: cb?.stats.avg_decode_tps ?? 0,
    }
  })

  const nameA = a.model_name.slice(0, 14)
  const nameB = b.model_name.slice(0, 14)

  return (
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={chartData}>
        <PolarGrid stroke="var(--border)" />
        <PolarAngleAxis dataKey="category" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
        <PolarRadiusAxis tick={{ fill: 'var(--text-secondary)', fontSize: 9 }} />
        <Radar name={nameA} dataKey={nameA} stroke={COLOR_A} fill={COLOR_A} fillOpacity={0.25} />
        <Radar name={nameB} dataKey={nameB} stroke={COLOR_B} fill={COLOR_B} fillOpacity={0.25} />
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }} />
        <Tooltip content={<CustomTooltip />} />
      </RadarChart>
    </ResponsiveContainer>
  )
}

// ── Latency comparison bar ─────────────────────────────────────────────────────
function LatencyCompareBar({ results }: { results: CompareResult[] }) {
  if (results.length < 2) return null
  const [a, b] = results

  const allCats = Array.from(new Set([
    ...a.by_category.map((c) => c.category),
    ...b.by_category.map((c) => c.category),
  ]))

  const chartData = allCats.map((cat) => {
    const ca = a.by_category.find((c) => c.category === cat)
    const cb = b.by_category.find((c) => c.category === cat)
    return {
      category: cat,
      [a.model_name.slice(0, 14)]: ca?.stats.latency?.avg != null ? +ca.stats.latency.avg.toFixed(0) : null,
      [b.model_name.slice(0, 14)]: cb?.stats.latency?.avg != null ? +cb.stats.latency.avg.toFixed(0) : null,
    }
  })

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="category" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
        <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} unit="ms" width={60} />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-secondary)' }} />
        <Bar dataKey={a.model_name.slice(0, 14)} fill={COLOR_A} radius={[3, 3, 0, 0]} />
        <Bar dataKey={b.model_name.slice(0, 14)} fill={COLOR_B} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── Model selector ─────────────────────────────────────────────────────────────
function ModelSelect({ label, value, options, onChange, exclude }: {
  label: string
  value: string
  options: string[]
  onChange: (v: string) => void
  exclude?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg px-3 py-2 text-sm outline-none"
        style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)', minWidth: 220 }}
      >
        <option value="">Select model…</option>
        {options.filter((o) => o !== exclude).map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function Compare() {
  const { data: models } = useModels()
  const [modelA, setModelA] = useState('')
  const [modelB, setModelB] = useState('')
  const { refresh } = useRefresh()

  const canCompare = !!modelA && !!modelB
  const { data: results, loading, error } = useCompare(
    canCompare ? [modelA, modelB] : [],
  )

  return (
    <div className="flex flex-col flex-1 overflow-auto">
      <Header title="Compare" subtitle="Side-by-side model comparison" onRefresh={refresh} />

      {/* Model selectors */}
      <div
        className="flex flex-wrap gap-6 px-6 py-4 border-b"
        style={{ borderColor: 'var(--border)' }}
      >
        <ModelSelect
          label="Model A"
          value={modelA}
          options={models ?? []}
          onChange={setModelA}
          exclude={modelB}
        />
        <ModelSelect
          label="Model B"
          value={modelB}
          options={models ?? []}
          onChange={setModelB}
          exclude={modelA}
        />
      </div>

      {!canCompare ? (
        <div className="flex-1 flex items-center justify-center">
          <EmptyState message="Select two models to compare" description="Use the dropdowns above to pick Model A and Model B." />
        </div>
      ) : loading ? (
        <div className="p-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <ChartSkeleton height={300} />
          <ChartSkeleton height={300} />
        </div>
      ) : error ? (
        <div className="p-6"><ErrorFallback error={error} /></div>
      ) : results && results.length >= 2 ? (
        <div className="p-6 flex flex-col gap-6">

          {/* Stats comparison table */}
          <div
            className="rounded-xl p-5"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <div className="grid grid-cols-3 mb-3">
              <span className="text-sm font-semibold truncate" style={{ color: COLOR_A }}>{results[0].model_name}</span>
              <span className="text-xs text-center font-medium" style={{ color: 'var(--text-secondary)' }}>Metric</span>
              <span className="text-sm font-semibold text-right truncate" style={{ color: COLOR_B }}>{results[1].model_name}</span>
            </div>
            <StatRow label="Total Tests" a={results[0].stats.total} b={results[1].stats.total} higherIsBetter />
            <StatRow label="Success Rate (%)" a={results[0].stats.success_rate} b={results[1].stats.success_rate} higherIsBetter />
            <StatRow label="Avg Latency" a={results[0].stats.latency?.avg} b={results[1].stats.latency?.avg} unit="ms" />
            <StatRow label="p95 Latency" a={results[0].stats.latency?.p95} b={results[1].stats.latency?.p95} unit="ms" />
            <StatRow label="Avg TTFT" a={results[0].stats.avg_ttft_ms} b={results[1].stats.avg_ttft_ms} unit="ms" />
            <StatRow label="Decode TPS" a={results[0].stats.avg_decode_tps} b={results[1].stats.avg_decode_tps} unit=" tps" higherIsBetter />
            <StatRow label="Prefill TPS" a={results[0].stats.avg_prefill_tps} b={results[1].stats.avg_prefill_tps} unit=" tps" higherIsBetter />
            <StatRow label="Native Mem" a={results[0].stats.avg_peak_native_mem_mb} b={results[1].stats.avg_peak_native_mem_mb} unit="MB" />
            <StatRow label="Java Mem" a={results[0].stats.avg_peak_java_mem_mb} b={results[1].stats.avg_peak_java_mem_mb} unit="MB" />
            <StatRow label="Avg Output Tokens" a={results[0].stats.avg_output_tokens} b={results[1].stats.avg_output_tokens} higherIsBetter />
          </div>

          {/* Charts row */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
              <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>Decode TPS by Category (Radar)</h2>
              <CategoryRadar results={results} />
            </div>
            <div className="rounded-xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
              <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>Avg Latency by Category</h2>
              <LatencyCompareBar results={results} />
            </div>
          </div>

        </div>
      ) : (
        <div className="p-6"><EmptyState message="No data for selected models" /></div>
      )}
    </div>
  )
}