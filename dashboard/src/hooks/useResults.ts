import { useState, useEffect, useCallback, useRef } from 'react'
import client, { ApiClientError } from '@/api/client'
import type {
  ResultItem,
  SummaryStats,
  ModelSummary,
  CategorySummary,
  CompareResult,
  PaginationMeta,
  Filters,
  ApiSuccess,
  RunItem,
} from '@/types'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

// ── Global refresh counter (shared across all hooks) ──────────────────────────
// FIX(R2): useRefresh now provides a tick that can be passed into individual hooks

let _globalTick = 0
const _listeners = new Set<() => void>()

function useGlobalRefreshTick(): number {
  const [tick, setTick] = useState(_globalTick)
  useEffect(() => {
    const listener = () => setTick(_globalTick)
    _listeners.add(listener)
    return () => { _listeners.delete(listener) }
  }, [])
  return tick
}

function useAsync<T>(fetchFn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null })
  const tick = useGlobalRefreshTick()

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

// ── Hooks ──────────────────────────────────────────────────────────────────────

export function useResults(filters: Filters) {
  const params = buildParams(filters)
  return useAsync<{ items: ResultItem[]; meta: PaginationMeta | null }>(
    async () => {
      const res = await client.get<ApiSuccess<ResultItem[]>>('/results', { params })
      return { items: res.data.data, meta: res.data.meta }
    },
    [JSON.stringify(params)],
  )
}

export function useSummary(filters: Omit<Filters, 'limit' | 'offset'>) {
  const params = buildParams(filters)
  return useAsync<SummaryStats>(
    async () => {
      const res = await client.get<ApiSuccess<SummaryStats>>('/results/summary', { params })
      return res.data.data
    },
    [JSON.stringify(params)],
  )
}

export function useByModel(filters?: { device?: string; category?: string; backend?: string }) {
  return useAsync<ModelSummary[]>(
    async () => {
      const res = await client.get<ApiSuccess<ModelSummary[]>>('/results/by-model', { params: filters })
      return res.data.data
    },
    [filters?.device, filters?.category, filters?.backend],
  )
}

export function useByCategory(filters?: { device?: string; model?: string; backend?: string }) {
  return useAsync<CategorySummary[]>(
    async () => {
      const res = await client.get<ApiSuccess<CategorySummary[]>>('/results/by-category', { params: filters })
      return res.data.data
    },
    [filters?.device, filters?.model, filters?.backend],
  )
}

export function useCompare(models: string[], device?: string, backend?: string) {
  return useAsync<CompareResult[]>(
    async () => {
      if (models.length < 2) return []
      const res = await client.get<ApiSuccess<CompareResult[]>>('/results/compare', {
        params: { models: models.join(','), device, backend },
      })
      return res.data.data
    },
    [models.join(','), device, backend],
  )
}

export function useDevices() {
  return useAsync<string[]>(
    async () => {
      const res = await client.get<ApiSuccess<string[]>>('/devices')
      return res.data.data
    },
    [],
  )
}

export function useModels(device?: string) {
  return useAsync<string[]>(
    async () => {
      const res = await client.get<ApiSuccess<string[]>>('/models', { params: { device } })
      return res.data.data
    },
    [device],
  )
}

export function useCategories() {
  return useAsync<string[]>(
    async () => {
      const res = await client.get<ApiSuccess<string[]>>('/categories')
      return res.data.data
    },
    [],
  )
}

export function useRunIds() {
  return useAsync<string[]>(
    async () => {
      const res = await client.get<ApiSuccess<string[]>>('/run-ids')
      return res.data.data
    },
    [],
  )
}

export function useRuns(status?: string, limit = 20, offset = 0) {
  return useAsync<{ items: RunItem[]; meta: PaginationMeta | null }>(
    async () => {
      const params: Record<string, string | number | undefined> = { limit, offset }
      if (status && status !== 'all') params.status = status
      const res = await client.get<ApiSuccess<RunItem[]>>('/runs', { params })
      return { items: res.data.data, meta: res.data.meta }
    },
    [status, limit, offset],
  )
}

// FIX(R2): useRefresh now triggers re-fetch in ALL hooks via global tick
export function useRefresh() {
  const refresh = useCallback(() => {
    _globalTick += 1
    _listeners.forEach((fn) => fn())
  }, [])
  return { refresh }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function buildParams(filters: Partial<Filters>): Record<string, string | number | undefined> {
  const p: Record<string, string | number | undefined> = {}
  if (filters.device) p.device = filters.device
  if (filters.model) p.model = filters.model
  if (filters.category) p.category = filters.category
  if (filters.backend) p.backend = filters.backend
  if (filters.status && filters.status !== 'all') p.status = filters.status
  if (filters.run_id) p.run_id = filters.run_id
  if ('limit' in filters && filters.limit !== undefined) p.limit = filters.limit
  if ('offset' in filters && filters.offset !== undefined) p.offset = filters.offset
  return p
}