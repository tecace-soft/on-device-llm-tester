import { useState, useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { Header } from '@/components/layout/Header'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useDevices, useModels } from '@/hooks/useResults'
import { useDeviceCompare } from '@/hooks/useDeviceCompare'
import type { DeviceCompareResult, SummaryStats } from '@/types'

const DEVICE_COLORS = ['#6c63ff', '#4caf7d', '#f0a965', '#f06565']

function fmt(v: number | null | undefined, decimals = 1): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function KpiCard({
  label,
  values,
  deviceNames,
  unit,
  lowerBetter,
}: {
  label: string
  values: (number | null | undefined)[]
  deviceNames: string[]
  unit: string
  lowerBetter?: boolean
}) {
  const valid = values.map((v) => (v != null ? v : null))
  const nums = valid.filter((v): v is number => v !== null)
  const bestIdx = nums.length > 0
    ? valid.indexOf(lowerBetter ? Math.min(...nums) : Math.max(...nums))
    : -1

  return (
    <div
      className="rounded-xl p-4 flex-1 min-w-[200px]"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div className="text-xs font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>{label}</div>
      <div className="flex flex-col gap-2">
        {deviceNames.map((name, i) => (
          <div key={name} className="flex items-center justify-between">
            <span className="text-xs" style={{ color: DEVICE_COLORS[i] }}>{name}</span>
            <span
              className="text-sm font-semibold"
              style={{ color: i === bestIdx ? 'var(--success)' : 'var(--text-primary)' }}
            >
              {fmt(valid[i])}{unit}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function DeviceInfoCard({ result }: { result: DeviceCompareResult }) {
  const info = result.device_info
  return (
    <div
      className="rounded-xl p-4 flex-1 min-w-[200px]"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div className="text-sm font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
        {result.device_model}
      </div>
      <div className="space-y-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
        <div>SoC: {info.soc || '—'}</div>
        <div>Android: {info.android_version || '—'} (SDK {info.sdk_int || '—'})</div>
        <div>CPU: {info.cpu_cores || '—'} cores · Heap: {info.max_heap_mb || '—'}MB</div>
        <div>OEM: {info.manufacturer || '—'}</div>
      </div>
    </div>
  )
}

export default function DeviceCompare() {
  const { data: allDevices } = useDevices()
  const [deviceA, setDeviceA] = useState<string>('')
  const [deviceB, setDeviceB] = useState<string>('')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const { data: models } = useModels()

  const selectedDevices = [deviceA, deviceB].filter(Boolean)
  const { data, loading, error, refresh } = useDeviceCompare(
    selectedDevices,
    selectedModel || undefined,
  )

  const chartData = useMemo(() => {
    if (!data || data.length < 2) return []
    const allCats = new Set<string>()
    data.forEach((d) => d.by_category.forEach((c) => allCats.add(c.category)))

    return Array.from(allCats).sort().map((cat) => {
      const point: Record<string, string | number | null> = { category: cat }
      data.forEach((d) => {
        const catData = d.by_category.find((c) => c.category === cat)
        point[`${d.device_model}_tps`] = catData?.stats.avg_decode_tps ?? null
      })
      return point
    })
  }, [data])

  const deviceNames = data?.map((d) => d.device_model) ?? []

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header
        title="Device Compare"
        subtitle="Compare benchmark performance across devices"
        onRefresh={refresh}
      />

      {/* Selection bar */}
      <div className="flex flex-wrap items-end gap-4 px-6 py-4 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Device A</label>
          <select
            value={deviceA}
            onChange={(e) => setDeviceA(e.target.value)}
            className="rounded-lg px-3 py-1.5 text-sm outline-none cursor-pointer"
            style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)', minWidth: 160 }}
          >
            <option value="">Select…</option>
            {(allDevices ?? []).map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Device B</label>
          <select
            value={deviceB}
            onChange={(e) => setDeviceB(e.target.value)}
            className="rounded-lg px-3 py-1.5 text-sm outline-none cursor-pointer"
            style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)', minWidth: 160 }}
          >
            <option value="">Select…</option>
            {(allDevices ?? []).filter((d) => d !== deviceA).map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Model</label>
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="rounded-lg px-3 py-1.5 text-sm outline-none cursor-pointer"
            style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)', minWidth: 220 }}
          >
            <option value="">All models</option>
            {(models ?? []).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 py-4 space-y-6">
        {selectedDevices.length < 2 && (
          <EmptyState
            message="Select two devices"
            description="Pick Device A and Device B above to compare their benchmark performance."
          />
        )}

        {selectedDevices.length >= 2 && loading && <LoadingSkeleton rows={6} />}
        {selectedDevices.length >= 2 && error && <ErrorFallback error={error} onRetry={refresh} />}

        {data && data.length >= 2 && (
          <>
            {/* Device info cards */}
            <div className="flex gap-4 flex-wrap">
              {data.map((d) => <DeviceInfoCard key={d.device_model} result={d} />)}
            </div>

            {/* KPI comparison */}
            <div className="flex gap-4 flex-wrap">
              <KpiCard
                label="Avg Latency"
                values={data.map((d) => d.stats.latency?.avg)}
                deviceNames={deviceNames}
                unit="ms"
                lowerBetter
              />
              <KpiCard
                label="Decode TPS"
                values={data.map((d) => d.stats.avg_decode_tps)}
                deviceNames={deviceNames}
                unit=" tps"
              />
              <KpiCard
                label="TTFT"
                values={data.map((d) => d.stats.avg_ttft_ms)}
                deviceNames={deviceNames}
                unit="ms"
                lowerBetter
              />
              <KpiCard
                label="Success Rate"
                values={data.map((d) => d.stats.success_rate)}
                deviceNames={deviceNames}
                unit="%"
              />
            </div>

            {/* Grouped bar chart — Decode TPS by category */}
            {chartData.length > 0 && (
              <div
                className="rounded-xl p-5"
                style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
              >
                <div className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
                  Decode TPS by Category
                </div>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={chartData} barCategoryGap="20%">
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="category" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
                    <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                      labelStyle={{ color: 'var(--text-primary)' }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {deviceNames.map((name, i) => (
                      <Bar
                        key={name}
                        dataKey={`${name}_tps`}
                        name={name}
                        fill={DEVICE_COLORS[i]}
                        radius={[4, 4, 0, 0]}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Detail table — category stats side by side */}
            <div
              className="rounded-xl overflow-hidden"
              style={{ border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              <div className="px-5 py-3 text-sm font-semibold" style={{ color: 'var(--text-primary)', borderBottom: '1px solid var(--border)' }}>
                Category Detail
              </div>
              <div className="overflow-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                      <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Category</th>
                      {deviceNames.map((name, i) => (
                        <th key={name} colSpan={3} className="px-2 py-2 text-center font-medium" style={{ color: DEVICE_COLORS[i] }}>
                          {name}
                        </th>
                      ))}
                    </tr>
                    <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                      <th />
                      {deviceNames.map((name) => (
                        <>
                          <th key={`${name}-lat`} className="px-2 py-1 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>Latency</th>
                          <th key={`${name}-tps`} className="px-2 py-1 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>Dec TPS</th>
                          <th key={`${name}-ttft`} className="px-2 py-1 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>TTFT</th>
                        </>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      const allCats = new Set<string>()
                      data.forEach((d) => d.by_category.forEach((c) => allCats.add(c.category)))
                      return Array.from(allCats).sort().map((cat) => (
                        <tr key={cat} style={{ borderBottom: '1px solid var(--border)' }}>
                          <td className="px-4 py-2 font-medium" style={{ color: 'var(--text-primary)' }}>{cat}</td>
                          {data.map((d) => {
                            const c = d.by_category.find((x) => x.category === cat)?.stats
                            return (
                              <>
                                <td key={`${d.device_model}-${cat}-lat`} className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>
                                  {fmt(c?.latency?.avg, 0)}ms
                                </td>
                                <td key={`${d.device_model}-${cat}-tps`} className="px-2 py-2 text-right" style={{ color: 'var(--text-primary)' }}>
                                  {fmt(c?.avg_decode_tps)}
                                </td>
                                <td key={`${d.device_model}-${cat}-ttft`} className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>
                                  {fmt(c?.avg_ttft_ms, 0)}ms
                                </td>
                              </>
                            )
                          })}
                        </tr>
                      ))
                    })()}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}