import { useState, useEffect } from 'react'
import client from '@/api/client'
import type { ApiSuccess, DeviceCompareResult } from '@/types'

interface UseDeviceCompareState {
  data: DeviceCompareResult[] | null
  loading: boolean
  error: string | null
}

export function useDeviceCompare(
  devices: string[],
  model?: string,
  backend?: string,
): UseDeviceCompareState & { refresh: () => void } {
  const [state, setState] = useState<UseDeviceCompareState>({
    data: null,
    loading: false,
    error: null,
  })
  const [tick, setTick] = useState(0)

  const key = devices.join(',')

  useEffect(() => {
    if (devices.length < 2) {
      setState({ data: null, loading: false, error: null })
      return
    }

    let cancelled = false
    setState({ data: null, loading: true, error: null })

    client
      .get<ApiSuccess<DeviceCompareResult[]>>('/results/compare-devices', {
        params: { devices: key, model, backend },
      })
      .then((res) => {
        if (!cancelled) setState({ data: res.data.data, loading: false, error: null })
      })
      .catch((err) => {
        if (!cancelled) setState({ data: null, loading: false, error: err.message || 'Failed to load' })
      })

    return () => { cancelled = true }
  }, [key, model, backend, tick])

  return { ...state, refresh: () => setTick((t) => t + 1) }
}