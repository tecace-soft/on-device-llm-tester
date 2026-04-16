import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { Header } from '@/components/layout/Header'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { useRuns, useRefresh } from '@/hooks/useResults'
import type { RunItem } from '@/types'

const GITHUB_REPO = 'https://github.com/tecace-soft/on-device-llm-tester'

type StatusFilter = 'all' | 'success' | 'error' | 'running'

function StatusBadge({ status }: { status: RunItem['status'] }) {
  const cfg = {
    success: { bg: 'rgba(76,175,125,0.15)', color: 'var(--success)', label: 'success' },
    error:   { bg: 'rgba(240,101,101,0.15)', color: 'var(--error)', label: 'error' },
    running: { bg: 'rgba(240,169,101,0.15)', color: '#f0a965', label: 'running' },
  }[status] ?? { bg: 'rgba(150,150,150,0.15)', color: 'var(--text-secondary)', label: status }

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: cfg.bg, color: cfg.color }}
    >
      {status === 'running' && (
        <span className="w-1.5 h-1.5 rounded-full mr-1.5 animate-pulse" style={{ background: '#f0a965' }} />
      )}
      {cfg.label}
    </span>
  )
}

function fmt(dt: string | null): string {
  if (!dt) return '—'
  return new Date(dt + 'Z').toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function duration(started: string | null, finished: string | null): string {
  if (!started || !finished) return '—'
  const s = new Date(started + 'Z').getTime()
  const f = new Date(finished + 'Z').getTime()
  const ms = f - s
  if (ms < 0) return '—'
  if (ms < 60000) return `${Math.round(ms / 1000)}s`
  return `${Math.round(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`
}

export default function RunHistory() {
  const navigate = useNavigate()
  const { refresh } = useRefresh()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [offset, setOffset] = useState(0)
  const limit = 20

  const { data, loading, error } = useRuns(statusFilter, limit, offset)
  const items = data?.items ?? []
  const meta = data?.meta

  const STATUS_OPTIONS: StatusFilter[] = ['all', 'success', 'error', 'running']

  function handleRowClick(run: RunItem) {
    navigate(`/raw?run_id=${run.run_id}`)
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header
        title="Run History"
        subtitle="GitHub Actions CI/CD benchmark runs"
        actions={
          <button
            onClick={refresh}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        }
      />

      {/* Status filter tabs */}
      <div className="flex items-center gap-2 px-6 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setOffset(0) }}
            className="px-3 py-1 rounded-lg text-xs font-medium transition-colors"
            style={{
              background: statusFilter === s ? 'var(--accent)' : 'var(--surface-2)',
              color: statusFilter === s ? '#fff' : 'var(--text-secondary)',
              border: '1px solid var(--border)',
            }}
          >
            {s === 'all' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
        {meta && (
          <span className="ml-auto text-xs" style={{ color: 'var(--text-secondary)' }}>
            {meta.total} run{meta.total !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {error && <ErrorFallback error={error} onRetry={refresh} />}
        {loading && <LoadingSkeleton rows={6} />}
        {!loading && !error && items.length === 0 && (
          <EmptyState
            message="No runs yet"
            description="Trigger a benchmark from GitHub Actions → Run workflow to see CI runs here."
          />
        )}
        {!loading && !error && items.length > 0 && (
          <div
            className="rounded-xl overflow-hidden"
            style={{ border: '1px solid var(--border)', background: 'var(--surface)' }}
          >
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                  {['Run ID', 'Status', 'Branch', 'Commit', 'Started', 'Duration', 'Results'].map((h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => handleRowClick(run)}
                    className="cursor-pointer transition-colors"
                    style={{ borderBottom: '1px solid var(--border)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-2)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    {/* Run ID */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-medium" style={{ color: 'var(--accent)' }}>
                          #{run.run_id}
                        </span>
                        <a
                          href={`${GITHUB_REPO}/actions/runs/${run.run_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          style={{ color: 'var(--text-secondary)' }}
                          title="Open in GitHub"
                        >
                          <ExternalLink size={11} />
                        </a>
                      </div>
                      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        {run.trigger}
                      </span>
                    </td>

                    {/* Status */}
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>

                    {/* Branch */}
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs" style={{ color: 'var(--text-primary)' }}>
                        {run.branch ?? '—'}
                      </span>
                    </td>

                    {/* Commit */}
                    <td className="px-4 py-3">
                      {run.commit_sha ? (
                        <a
                          href={`${GITHUB_REPO}/commit/${run.commit_sha}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="font-mono text-xs hover:underline"
                          style={{ color: 'var(--accent)' }}
                        >
                          {run.commit_sha.slice(0, 7)}
                        </a>
                      ) : (
                        <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>—</span>
                      )}
                    </td>

                    {/* Started */}
                    <td className="px-4 py-3 text-xs whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                      {fmt(run.started_at)}
                    </td>

                    {/* Duration */}
                    <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {duration(run.started_at, run.finished_at)}
                    </td>

                    {/* Result count */}
                    <td className="px-4 py-3 text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                      {run.result_count ?? 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {meta && meta.total > limit && (
        <div
          className="flex items-center justify-between px-6 py-3 border-t shrink-0"
          style={{ borderColor: 'var(--border)' }}
        >
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {offset + 1}–{Math.min(offset + limit, meta.total)} of {meta.total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
            >
              Previous
            </button>
            <button
              disabled={!meta.has_more}
              onClick={() => setOffset(offset + limit)}
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