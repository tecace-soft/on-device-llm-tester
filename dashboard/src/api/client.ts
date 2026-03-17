import axios, { AxiosError } from 'axios'
import type { ApiResponse } from '@/types'

const client = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Optional API key injection
const apiKey = import.meta.env.VITE_API_KEY
if (apiKey) {
  client.defaults.headers.common['X-API-Key'] = apiKey
}

// Response interceptor — unwrap or throw normalized error
client.interceptors.response.use(
  (response) => {
    const data = response.data as ApiResponse<unknown>
    if (data.status === 'error') {
      throw new ApiClientError(data.error, data.detail)
    }
    return response
  },
  (error: AxiosError) => {
    if (error.response) {
      const data = error.response.data as { error?: string; detail?: string }
      const msg = data?.error ?? `HTTP ${error.response.status}`
      const detail = data?.detail
      if (error.response.status === 401) {
        throw new ApiClientError('Unauthorized — check API key', detail)
      }
      throw new ApiClientError(msg, detail)
    }
    if (error.request) {
      throw new ApiClientError('Network error — API server unreachable')
    }
    throw new ApiClientError(error.message)
  },
)

export class ApiClientError extends Error {
  detail?: string
  constructor(message: string, detail?: string) {
    super(message)
    this.name = 'ApiClientError'
    this.detail = detail
  }
}

export default client