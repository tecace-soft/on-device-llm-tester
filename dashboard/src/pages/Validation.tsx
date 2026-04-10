import { ShieldCheck, ShieldAlert, ShieldQuestion, AlertTriangle, SkipForward } from 'lucide-react'
import { Header } from '@/components/layout/Header'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { CategoryValidationChart } from '@/components/validation/CategoryValidationChart'
import { ModelValidationChart } from '@/components/validation/ModelValidationChart'
import { FailLog } from '@/components/validation/FailLog'
import { QuantDiffTable } from '@/components/validation/QuantDiffTable'
import { useValidationSummary, useValidationRefresh } from '@/hooks/useValidation'
import { useDevices, useModels } from '@/hooks/useResults'
import { useState } from 'react'

function KpiCard({ label, value, sub, icon: Icon, color }: {
  label: string
  value: string | number
  sub?: string
  icon: any
  color: string
}) {
  return (
    <div
      className="flex items-center gap-4 rounded-xl px-5 py-4 flex-1 min-w-[180px]"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div
        className="flex items-center justify-center w-10 h-10 rounded-lg"
        style={{ background: `${color}18` }}
      >
        <Icon size={18} style={{ color }} />
      </div>
      <div>
        <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</p>
        <p className="text-xl font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{value}</p>
        {sub && <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-secondary)' }}>{sub}</p>}
      </div>
    </div>
  )
}

export default function Validation() {
  const { refresh } = useValidationRefresh()
  const [device, setDevice] = useState<string | undefined>()
  const [model, setModel] = useState<string | undefined>()

  const { data: devices } = useDevices()
  const { data: models } = useModels(device)
  const { data: summary, loading, error } = useValidationSummary({ device, model })

  const filters = { device, model }

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="Response Validation"
        subtitle="Deterministic correctness checks on LLM responses"
        onRefresh={refresh}
      />

      {/* Filters */}
      <div
        className="flex items-center gap-3 px-6 py-3 border-b"
        style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
      >
        <select
          value={device ?? ''}
          onChange={(e) => { setDevice(e.target.value || undefined); setModel(undefined) }}
          className="px-3 py-1.5 rounded-lg text-xs"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All Devices</option>
          {(devices ?? []).map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select
          value={model ?? ''}
          onChange={(e) => setModel(e.target.value || undefined)}
          className="px-3 py-1.5 rounded-lg text-xs"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All Models</option>
          {(models ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
        {loading && <LoadingSkeleton rows={6} />}
        {error && <ErrorFallback error={error} onRetry={refresh} />}

        {summary && (
          <>
            {/* KPI Cards */}
            <div className="flex gap-4 flex-wrap">
              <KpiCard
                label="Pass Rate"
                value={`${(summary.pass_rate * 100).toFixed(1)}%`}
                sub={`${summary.pass_count} of ${summary.total - summary.skip_count} evaluable`}
                icon={ShieldCheck}
                color="#4caf7d"
              />
              <KpiCard
                label="Failures"
                value={summary.fail_count}
                sub={summary.fail_count > 0 ? 'Incorrect or invalid' : 'No failures'}
                icon={ShieldAlert}
                color="#f06565"
              />
              <KpiCard
                label="Warnings"
                value={summary.warn_count}
                sub="Truncated or gibberish"
                icon={AlertTriangle}
                color="#f0a965"
              />
              <KpiCard
                label="Uncertain"
                value={summary.uncertain_count}
                sub="Needs LLM judge (4b)"
                icon={ShieldQuestion}
                color="#8b90b0"
              />
              <KpiCard
                label="Skipped"
                value={summary.skip_count}
                sub="Error status or no eval"
                icon={SkipForward}
                color="#6c63ff"
              />
            </div>

            {summary.total === 0 && (
              <EmptyState
                message="No validation results yet"
                description="Run response_validator.py after ingest to generate validation data."
              />
            )}
          </>
        )}

        {summary && summary.total > 0 && (
          <>
            {/* Charts */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              <CategoryValidationChart filters={filters} />
              <ModelValidationChart filters={filters} />
            </div>

            {/* Result Log */}
            <FailLog filters={filters} />

            {/* Quant Diff — response similarity across all model pairs */}
            <QuantDiffTable filters={{ device }} />
          </>
        )}
      </div>
    </div>
  )
}