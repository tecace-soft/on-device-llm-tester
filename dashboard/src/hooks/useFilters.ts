import { useState, useCallback } from 'react'
import type { Filters } from '@/types'

const DEFAULT_FILTERS: Filters = {
  device: undefined,
  model: undefined,
  category: undefined,
  backend: undefined,
  status: undefined,
  limit: 50,
  offset: 0,
}

export function useFilters() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)

  const setFilter = useCallback(<K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value, offset: 0 }))
  }, [])

  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), [])

  const setPage = useCallback((offset: number) => {
    setFilters((prev) => ({ ...prev, offset }))
  }, [])

  return { filters, setFilter, resetFilters, setPage }
}