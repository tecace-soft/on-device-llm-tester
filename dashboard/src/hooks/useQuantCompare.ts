/**
 * Quant Compare data hook — parallel fetch of comparison + similarity APIs.
 * Architecture: QUANT_COMPARISON_ARCHITECTURE.md §8.4
 * Depends on: api/client.ts, types/index.ts (Quant* interfaces)
 * Used by: pages/QuantCompare.tsx
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import client, { ApiClientError } from '@/api/client'
import type {
  ApiSuccess,
  QuantComparisonResponse,
  QuantSimilarityResponse,
} from '@/types'

interface UseQuantCompareParams {
  device?: string
  baseModel?: string
}

interface UseQuantCompareResult {
  comparison: QuantComparisonResponse | null
  similarity: QuantSimilarityResponse | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useQuantCompare({ device, baseModel }: UseQuantCompareParams): UseQuantCompareResult {
  const [comparison, setComparison] = useState<QuantComparisonResponse | null>(null)
  const [similarity, setSimilarity] = useState<QuantSimilarityResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchKey = useMemo(() => `${device ?? ''}|${baseModel ?? ''}`, [device, baseModel])

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string> = {}
      if (device) params.device = device
      if (baseModel) params.base_model = baseModel

      const [compRes, simRes] = await Promise.allSettled([
        client.get<ApiSuccess<QuantComparisonResponse>>('/quant/comparison', { params }),
        client.get<ApiSuccess<QuantSimilarityResponse>>('/quant/similarity', { params }),
      ])

      if (compRes.status === 'fulfilled') setComparison(compRes.value.data.data)
      else setComparison(null)

      if (simRes.status === 'fulfilled') setSimilarity(simRes.value.data.data)
      else setSimilarity(null)

      if (compRes.status === 'rejected' && simRes.status === 'rejected') {
        const msg = compRes.reason instanceof ApiClientError
          ? compRes.reason.message
          : 'Failed to load quant comparison data'
        setError(msg)
      }
    } catch (e: any) {
      setError(e.message ?? 'Unknown error')
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchKey])

  useEffect(() => { fetchData() }, [fetchData])

  return { comparison, similarity, loading, error, refresh: fetchData }
}
