import { useState, useEffect, useCallback } from 'react'
import client, { ApiClientError } from '@/api/client'
import type { ApiSuccess, ValidationSummary, CategoryValidation, ModelValidation, QuantDiffItem } from '@/types'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

// Reuse the same global tick mechanism from useResults
let _vTick = 0
const _vListeners = new Set<() => void>()

function useVTick(): number {
  const [tick, setTick] = useState(_vTick)
  useEffect(() => {
    const listener = () => setTick(_vTick)
    _vListeners.add(listener)
    return () => { _vListeners.delete(listener) }
  }, [])
  return tick
}

export function useValidationRefresh() {
  const refresh = useCallback(() => {
    _vTick += 1
    _vListeners.forEach((fn) => fn())
  }, [])
  return { refresh }
}

function useVAsync<T>(fetchFn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null })
  const tick = useVTick()

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, error: null })
    fetchFn()
      .then((data) => { if (!cancelled) setState({ data, loading: false, error: null }) })
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof ApiClientError ? err.message : 'Unexpected error'
          setState({ data: null, loading: false, error: msg })
        }
      })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return state
}

export function useValidationSummary(filters?: { device?: string; model?: string; run_id?: string }) {
  return useVAsync<ValidationSummary>(
    async () => {
      const res = await client.get<ApiSuccess<ValidationSummary>>('/validation/summary', { params: filters })
      return res.data.data
    },
    [filters?.device, filters?.model, filters?.run_id],
  )
}

export function useValidationByCategory(filters?: { device?: string; model?: string }) {
  return useVAsync<CategoryValidation[]>(
    async () => {
      const res = await client.get<ApiSuccess<CategoryValidation[]>>('/validation/by-category', { params: filters })
      return res.data.data
    },
    [filters?.device, filters?.model],
  )
}

export function useValidationByModel(filters?: { device?: string }) {
  return useVAsync<ModelValidation[]>(
    async () => {
      const res = await client.get<ApiSuccess<ModelValidation[]>>('/validation/by-model', { params: filters })
      return res.data.data
    },
    [filters?.device],
  )
}

export function useQuantDiff(filters?: { device?: string }) {
  return useVAsync<QuantDiffItem[]>(
    async () => {
      const res = await client.get<ApiSuccess<QuantDiffItem[]>>('/validation/quant-diff', { params: filters })
      return res.data.data
    },
    [filters?.device],
  )
}