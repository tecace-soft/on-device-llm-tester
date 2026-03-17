import { useState, useMemo } from 'react'
import { Search, ChevronDown, ChevronUp } from 'lucide-react'
import { Header } from '@/components/layout/Header'
import { FilterBar } from '@/components/filters/FilterBar'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useResults, useRefresh } from '@/hooks/useResults'
import { useFilters } from '@/hooks/useFilters'
import type { ResultItem, ResultSuccess } from '@/types'

function ResponseCard({ item }: { item: ResultItem }) {
  const [expanded, setExpanded] = useState(false)
  const isSuccess = item.status === 'success'
  const s = isSuccess ? (item as ResultSuccess) : null

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      {/* Header row */}
      <button
        className="w-full flex items-center justify-between px-5 py-3 text-left"
        onClick={() => setExpanded((v) => !v)}
        style={{ background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full shrink-0"
            style={{
              background: isSuccess ? 'rgba(76,175,125,0.15)' : 'rgba(240,101,101,0.15)',
              color: isSuccess ? 'var(--success)' : 'var(--error)',
            }}
          >
            {item.status}
          </span>
          <span className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>
            [{item.prompt_category}]
          </span>
          <span className="text-sm truncate" style={{ color: 'var(--text-primary)' }}>
            {item.prompt.slice(0, 120)}{item.prompt.length > 120 ? '…' : ''}
          </span>
        </div>
        <div className="flex items-center gap-4 shrink-0 ml-4">
          {s?.latency_ms != null && (
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {s.latency_ms.toFixed(0)}ms
            </span>
          )}
          {s?.metrics?.decode_tps != null && (
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {s.metrics.decode_tps.toFixed(1)} tps
            </span>
          )}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t" style={{ borderColor: 'var(--border)' }}>
          <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x" style={{ '--tw-divide-opacity': 1 } as any}>
            <div className="p-5">
              <p className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>PROMPT</p>
              <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{item.prompt}</p>
            </div>
            <div className="p-5">
              <p className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>RESPONSE</p>
              {isSuccess ? (
                <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{item.response || '(empty)'}</p>
              ) : (
                <p className="text-sm" style={{ color: 'var(--error)' }}>{(item as any).error}</p>
              )}
            </div>
          </div>
          {s && (
            <div className="px-5 py-3 border-t flex flex-wrap gap-4 text-xs" style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}>
              <span>Model: <strong style={{ color: 'var(--text-primary)' }}>{s.model_name}</strong></span>
              <span>Backend: <strong style={{ color: 'var(--text-primary)' }}>{s.backend}</strong></span>
              <span>Input tokens: <strong style={{ color: 'var(--text-primary)' }}>{s.metrics?.input_token_count ?? '—'}</strong></span>
              <span>Output tokens: <strong style={{ color: 'var(--text-primary)' }}>{s.metrics?.output_token_count ?? '—'}</strong></span>
              <span>TTFT: <strong style={{ color: 'var(--text-primary)' }}>{s.metrics?.ttft_ms?.toFixed(0) ?? '—'}ms</strong></span>
              <span>Init time: <strong style={{ color: 'var(--text-primary)' }}>{s.init_time_ms?.toFixed(0) ?? '—'}ms</strong></span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Responses() {
  const { filters, setFilter, resetFilters } = useFilters()
  const { refresh } = useRefresh()
  const [search, setSearch] = useState('')

  const { data: results, loading, error } = useResults({ ...filters, limit: 200, offset: 0 })

  const items = useMemo(() => {
    const all = results?.items ?? []
    if (!search.trim()) return all
    const q = search.toLowerCase()
    return all.filter(
      (r) => r.prompt.toLowerCase().includes(q) || r.response?.toLowerCase().includes(q),
    )
  }, [results, search])

  return (
    <div className="flex flex-col flex-1 overflow-auto">
      <Header title="Responses" subtitle="Prompt & response quality viewer" onRefresh={refresh} />
      <FilterBar filters={filters} onFilter={setFilter} onReset={resetFilters} />

      {/* Search bar */}
      <div className="px-6 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <div
          className="flex items-center gap-2 rounded-lg px-3 py-2"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}
        >
          <Search size={14} style={{ color: 'var(--text-secondary)' }} />
          <input
            type="text"
            placeholder="Search prompts & responses…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: 'var(--text-primary)' }}
          />
          {search && (
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {items.length} results
            </span>
          )}
        </div>
      </div>

      <div className="p-6 flex flex-col gap-3">
        {loading ? (
          <LoadingSkeleton rows={5} />
        ) : error ? (
          <ErrorFallback error={error} />
        ) : items.length === 0 ? (
          <EmptyState message="No responses found" description="Try adjusting filters or search query." />
        ) : (
          items.map((item, i) => <ResponseCard key={`${item.prompt_id}-${i}`} item={item} />)
        )}
      </div>
    </div>
  )
}