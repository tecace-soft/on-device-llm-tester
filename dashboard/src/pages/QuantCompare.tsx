/**
 * QuantCompare page — quantization trade-off analysis dashboard.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.2
 * Depends on: useQuantCompare, useDevices (hooks), all quant/* components
 */
import { useState, useMemo } from 'react'
import { Header } from '@/components/layout/Header'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { EmptyState } from '@/components/feedback/EmptyState'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { InsightCards } from '@/components/quant/InsightCards'
import { ComparisonTable } from '@/components/quant/ComparisonTable'
import { TradeoffRadar } from '@/components/quant/TradeoffRadar'
import { SimilarityMatrix } from '@/components/quant/SimilarityMatrix'
import { CategorySimilarity } from '@/components/quant/CategorySimilarity'
import { useQuantCompare } from '@/hooks/useQuantCompare'
import { useDevices } from '@/hooks/useResults'

export default function QuantCompare() {
  const [device, setDevice] = useState<string | undefined>()
  const [baseModel, setBaseModel] = useState<string | undefined>()

  const { data: devices } = useDevices()
  const { comparison, similarity, loading, error, refresh } = useQuantCompare({ device, baseModel })

  const baseModels = useMemo(() => {
    if (!comparison) return []
    return comparison.groups.map((g) => g.base_model)
  }, [comparison])

  const hasData = comparison && comparison.groups.length > 0

  return (
    <div className="flex flex-col h-screen">
      <Header
        title="Quant Compare"
        subtitle="Quantization trade-off analysis"
        onRefresh={refresh}
      />

      {/* Filters */}
      <div
        className="flex items-center gap-3 px-6 py-3 border-b"
        style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
      >
        <select
          value={device ?? ''}
          onChange={(e) => setDevice(e.target.value || undefined)}
          className="px-3 py-1.5 rounded-lg text-xs"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All Devices</option>
          {(devices ?? []).map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select
          value={baseModel ?? ''}
          onChange={(e) => setBaseModel(e.target.value || undefined)}
          className="px-3 py-1.5 rounded-lg text-xs"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All Base Models</option>
          {baseModels.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
        {loading && <LoadingSkeleton rows={6} />}
        {error && <ErrorFallback error={error} onRetry={refresh} />}

        {!loading && !error && !hasData && (
          <EmptyState
            message="No quantization comparison data"
            description="Run benchmarks with multiple quantization levels of the same model to see comparisons here."
          />
        )}

        {hasData && (
          <>
            {/* Insight Cards */}
            <InsightCards groups={comparison!.groups} />

            {/* Comparison Tables — one per group */}
            {comparison!.groups.map((g) => (
              <ComparisonTable key={g.base_model} group={g} />
            ))}

            {/* Charts row */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              {comparison!.groups.map((g) => (
                <TradeoffRadar key={g.base_model} group={g} />
              ))}

              {similarity && (
                <SimilarityMatrix similarity={similarity} />
              )}
            </div>

            {/* Category Similarity */}
            {similarity && similarity.by_category.length > 0 && (
              <CategorySimilarity byCategory={similarity.by_category} overallAvg={similarity.overall_avg_ratio} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
