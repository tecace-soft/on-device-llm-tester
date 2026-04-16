import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useResults } from '@/hooks/useResults'
import type { ResultItem } from '@/types'

interface Props {
  filters?: { device?: string; model?: string }
}

export function FailLog({ filters }: Props) {
  const { data, loading, error } = useResults({
    ...filters,
    status: 'all' as any,
    limit: 200,
    offset: 0,
  })

  if (loading) return <LoadingSkeleton rows={5} />
  if (error) return <ErrorFallback error={error} />

  // Filter to only show fail/warn/uncertain results
  // Note: validation_status is embedded in the result from API
  // For now, show all non-pass results from the full result set
  const items = data?.items ?? []
  if (!items.length) return <EmptyState message="No results found" />

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div className="px-5 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Recent Results
        </h3>
        <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
          All test results with status and response preview
        </p>
      </div>

      <div className="overflow-auto max-h-[400px]">
        <table className="w-full text-sm border-collapse">
          <thead style={{ background: 'var(--surface)', position: 'sticky', top: 0, zIndex: 1 }}>
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Status</th>
              <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Prompt</th>
              <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Category</th>
              <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Model</th>
              <th className="px-4 py-2 text-left text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Response</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 50).map((item, i) => (
              <FailLogRow key={i} item={item} even={i % 2 === 0} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FailLogRow({ item, even }: { item: ResultItem; even: boolean }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr
        className="border-b cursor-pointer hover:opacity-80"
        style={{ borderColor: 'var(--border)', background: even ? 'transparent' : 'var(--surface)' }}
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="px-4 py-2">
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-medium"
            style={{
              background: item.status === 'success' ? 'rgba(76,175,125,0.15)' : 'rgba(240,101,101,0.15)',
              color: item.status === 'success' ? 'var(--success)' : 'var(--error)',
            }}
          >
            {item.status}
          </span>
        </td>
        <td className="px-4 py-2 text-xs max-w-[250px] truncate" style={{ color: 'var(--text-primary)' }}>
          {item.prompt_id}
        </td>
        <td className="px-4 py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
          {item.prompt_category}
        </td>
        <td className="px-4 py-2 text-xs max-w-[150px] truncate" style={{ color: 'var(--text-secondary)' }}>
          {item.model_name}
        </td>
        <td className="px-4 py-2 text-xs max-w-[300px] truncate" style={{ color: 'var(--text-secondary)' }}>
          {item.status === 'error' ? (item.error || '(error)') : (item.response?.slice(0, 80) || '(empty)')}
          <span className="ml-2 inline-block">
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </span>
        </td>
      </tr>
      {expanded && (
        <tr style={{ background: 'var(--surface-2)' }}>
          <td colSpan={5} className="px-4 py-3">
            <div className="space-y-2 text-xs">
              <div>
                <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>Prompt: </span>
                <span style={{ color: 'var(--text-primary)' }}>{item.prompt}</span>
              </div>
              <div>
                <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>Response: </span>
                <span className="whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>
                  {item.status === 'error' ? (item.error || '(error)') : (item.response || '(empty)')}
                </span>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}