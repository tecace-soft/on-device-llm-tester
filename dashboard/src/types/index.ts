// ── Device & Metrics ───────────────────────────────────────────────────────────

export interface DeviceInfo {
  manufacturer: string
  model: string
  product: string
  soc: string
  android_version: string
  sdk_int: number
  cpu_cores: number
  max_heap_mb: number
}

export interface Metrics {
  ttft_ms: number | null
  prefill_time_ms: number | null
  decode_time_ms: number | null
  input_token_count: number | null
  output_token_count: number | null
  prefill_tps: number | null
  decode_tps: number | null
  peak_java_memory_mb: number | null
  peak_native_memory_mb: number | null
  itl_p50_ms: number | null
  itl_p95_ms: number | null
  itl_p99_ms: number | null
}

// ── Result shapes ──────────────────────────────────────────────────────────────

export interface ResultSuccess {
  status: 'success'
  prompt_id: string
  prompt_category: string
  prompt_lang: string
  model_name: string
  model_path: string
  backend: 'CPU' | 'GPU'
  device: DeviceInfo
  prompt: string
  response: string
  latency_ms: number
  init_time_ms: number
  metrics: Metrics
  timestamp: number
  run_id: string | null
}

export interface ResultError {
  status: 'error'
  prompt_id: string
  prompt_category: string
  model_name: string
  device: DeviceInfo
  prompt: string
  response: string
  error: string
  metrics: null
  timestamp: number
  run_id: string | null
}

export type ResultItem = ResultSuccess | ResultError

// ── API response wrappers ──────────────────────────────────────────────────────

export interface PaginationMeta {
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface ApiSuccess<T> {
  status: 'ok'
  data: T
  meta: PaginationMeta | null
}

export interface ApiError {
  status: 'error'
  error: string
  detail?: string
}

export type ApiResponse<T> = ApiSuccess<T> | ApiError

// ── Stats / Summary ────────────────────────────────────────────────────────────

export interface PercentileStats {
  p50: number
  p95: number
  p99: number
  avg: number
  min: number
  max: number
}

export interface SummaryStats {
  total: number
  success: number
  errors: number
  success_rate: number
  latency: PercentileStats | null
  avg_ttft_ms: number | null
  avg_decode_tps: number | null
  avg_prefill_tps: number | null
  avg_init_time_ms: number | null
  avg_peak_native_mem_mb: number | null
  avg_peak_java_mem_mb: number | null
  avg_output_tokens: number | null
}

export interface ModelSummary {
  model_name: string
  stats: SummaryStats
}

export interface CategorySummary {
  category: string
  stats: SummaryStats
}

export interface CompareResult {
  model_name: string
  stats: SummaryStats
  by_category: CategorySummary[]
}

// ── Filter state ───────────────────────────────────────────────────────────────

export interface Filters {
  device?: string
  model?: string
  category?: string
  backend?: string
  status?: 'success' | 'error' | 'all'
  run_id?: string
  limit: number
  offset: number
}

// ── CI/CD Run (Phase 2) ────────────────────────────────────────────────────────

export interface RunItem {
  id: number
  run_id: string
  trigger: string
  commit_sha: string | null
  branch: string | null
  started_at: string | null
  finished_at: string | null
  status: 'running' | 'success' | 'error'
  result_count: number | null
}