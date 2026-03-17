import { useState } from 'react'
import { Download, ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { Header } from '@/components/layout/Header'
import { FilterBar } from '@/components/filters/FilterBar'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useResults, useRefresh } from '@/hooks/useResults'
import { useFilters } from '@/hooks/useFilters'
import type { ResultItem, ResultSuccess } from '@/types'

type SortKey = 'status' | 'model_name' | 'prompt_category' | 'latency_ms' | 'decode_tps' | 'backend'
type SortDir = 'asc' | 'desc'

function SortIcon({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  if (col !== sortKey) return <ChevronsUpDown size={12} style={{ opacity: 0.4 }} />
  return sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
}

function Th({ label, col, sortKey, sortDir, onSort }: {
  label: string; col: SortKey; sortKey: SortKey; sortDir: SortDir; onSort: (c: SortKey) => void
}) {
  return (
    <th
      className="px-3 py-2 text-left text-xs font-medium cursor-pointer select-none whitespace-nowrap"
      style={{ color: 'var(--text-secondary)' }}
      onClick={() => onSort(col)}
    >
      <span className="flex items-center gap-1">
        {label}
        <SortIcon col={col} sortKey={sortKey} sortDir={sortDir} />
      </span>
    </th>
  )
}

function fmt(v: number | null | undefined, d = 1) {
  return v != null ? v.toFixed(d) : '—'
}

export default function RawData() {
  const { filters, setFilter, resetFilters, setPage } = useFilters()
  const { refresh } = useRefresh()
  const [sortKey, setSortKey] = useState<SortKey>('latency_ms')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const { data: results, loading, error } = useResults(filters)
  const items = results?.items ?? []
  const meta = results?.meta

  // client-side sort
  const sorted = [...items].sort((a, b) => {
    const mul = sortDir === 'asc' ? 1 : -1
    const va = getValue(a, sortKey)
    const vb = getValue(b, sortKey)
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    return typeof va === 'string' ? mul * va.localeCompare(vb as string) : mul * ((va as number) - (vb as number))
  })

  function handleSort(col: SortKey) {
    if (col === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(col); setSortDir('asc') }
  }

  function handleExport() {
    const params = new URLSearchParams()
    if (filters.device) params.set('device', filters.device)
    if (filters.model) params.set('model', filters.model)
    if (filters.category) params.set('category', filters.category)
    if (filters.backend) params.set('backend', filters.backend)
    if (filters.status) params.set('status', filters.status)
    window.open(`/api/export/csv?${params.toString()}`, '_blank')
  }

  return (
    <div className="flex flex-col flex-1 overflow-auto">
      <Header title="Raw Data" subtitle="Full results table with export" onRefresh={refresh} />
      <FilterBar filters={filters} onFilter={setFilter} onReset={resetFilters} />

      {/* Toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          {meta ? `${meta.total} total results` : ''}
        </span>
        <button
          onClick={handleExport}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
          style={{ background: 'var(--accent)', color: '#fff' }}
        >
          <Download size={13} />
          Export CSV
        </button>
      </div>

      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-6"><LoadingSkeleton rows={8} /></div>
        ) : error ? (
          <div className="p-6"><ErrorFallback error={error} /></div>
        ) : sorted.length === 0 ? (
          <div className="p-6"><EmptyState message="No results" /></div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead style={{ background: 'var(--surface)', position: 'sticky', top: 0, zIndex: 1 }}>
              <tr>
                <Th label="Status" col="status" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th label="Model" col="model_name" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th label="Category" col="prompt_category" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th label="Backend" col="backend" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th label="Latency" col="latency_ms" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <Th label="Decode TPS" col="decode_tps" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-left text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Prompt</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((item, i) => {
                const s = item.status === 'success' ? (item as ResultSuccess) : null
                return (
                  <tr
                    key={i}
                    className="border-b"
                    style={{ borderColor: 'var(--border)', background: i % 2 === 0 ? 'transparent' : 'var(--surface)' }}
                  >
                    <td className="px-3 py-2">
                      <span
                        className="text-xs px-2 py-0.5 rounded-full"
                        style={{
                          background: item.status === 'success' ? 'rgba(76,175,125,0.15)' : 'rgba(240,101,101,0.15)',
                          color: item.status === 'success' ? 'var(--success)' : 'var(--error)',
                        }}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs max-w-[160px] truncate" style={{ color: 'var(--text-secondary)' }}>{item.model_name}</td>
                    <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>{item.prompt_category}</td>
                    <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>{s?.backend ?? '—'}</td>
                    <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-primary)' }}>{fmt(s?.latency_ms, 0)}ms</td>
                    <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-primary)' }}>{fmt(s?.metrics?.decode_tps)} tps</td>
                    <td className="px-3 py-2 text-xs max-w-[300px] truncate" style={{ color: 'var(--text-secondary)' }}>{item.prompt}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {meta && (
        <div
          className="flex items-center justify-between px-6 py-3 border-t shrink-0"
          style={{ borderColor: 'var(--border)' }}
        >
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {filters.offset + 1}–{Math.min(filters.offset + filters.limit, meta.total)} of {meta.total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={filters.offset === 0}
              onClick={() => setPage(Math.max(0, filters.offset - filters.limit))}
              className="px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            >
              Previous
            </button>
            <button
              disabled={!meta.has_more}
              onClick={() => setPage(filters.offset + filters.limit)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function getValue(item: ResultItem, key: SortKey): string | number | null {
  switch (key) {
    case 'status': return item.status
    case 'model_name': return item.model_name
    case 'prompt_category': return item.prompt_category
    case 'backend': return item.status === 'success' ? (item as ResultSuccess).backend : null
    case 'latency_ms': return item.status === 'success' ? (item as ResultSuccess).latency_ms : null
    case 'decode_tps': return item.status === 'success' ? ((item as ResultSuccess).metrics?.decode_tps ?? null) : null
    default: return null
  }
}