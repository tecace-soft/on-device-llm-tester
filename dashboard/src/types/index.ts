// ── API wrapper ─────────────────────────────────────────────────────────────

export interface PaginationMeta {
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface ApiSuccess<T> {
  status: 'ok'
  data: T
  meta?: PaginationMeta | null
}

export interface ApiError {
  status: 'error'
  error: string
  detail?: string
}

export type ApiResponse<T> = ApiSuccess<T> | ApiError

// ── Device / Metrics ────────────────────────────────────────────────────────

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

// ── Phase 6: Resource Profile ───────────────────────────────────────────────

export interface ResourceProfile {
  battery_level_start: number | null
  battery_level_end: number | null
  battery_delta: number | null
  thermal_start: number | null
  thermal_end: number | null
  thermal_delta: number | null
  thermal_start_celsius: number | null
  thermal_end_celsius: number | null
  voltage_start_mv: number | null
  voltage_end_mv: number | null
  voltage_delta_mv: number | null
  current_before_ua: number | null
  current_after_ua: number | null
  current_delta_ua: number | null
  system_pss_mb: number | null
  profiling_error: string | null
}

export interface ResourceSummary {
  avg_thermal_delta_celsius: number | null
  avg_voltage_delta_mv: number | null
  avg_current_delta_ua: number | null
  avg_system_pss_mb: number | null
  profiling_coverage: number | null
}

// ── Result ──────────────────────────────────────────────────────────────────

export type ResultStatus = 'success' | 'error'

export interface ResultItem {
  status: ResultStatus
  prompt_id: string
  prompt_category: string
  prompt_lang: string
  model_name: string
  model_path: string
  backend: string
  engine: string
  device: DeviceInfo
  prompt: string
  response: string
  latency_ms: number | null
  init_time_ms: number | null
  metrics: Metrics | null
  error: string | null
  timestamp: number | null
  run_id: string | null
  resource_profile: ResourceProfile | null
}

export type ResultSuccess = ResultItem & { status: 'success'; latency_ms: number; backend: string }

// ── Summary / Aggregate ─────────────────────────────────────────────────────

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
  resource: ResourceSummary | null
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

// ── CI/CD Run (Phase 2) ────────────────────────────────────────────────────

export type RunStatus = 'running' | 'success' | 'error'

export interface RunItem {
  id: number
  run_id: string
  trigger: string
  commit_sha: string | null
  branch: string | null
  started_at: string | null
  finished_at: string | null
  status: RunStatus
  result_count: number | null
}

// ── Device Compare (Phase 3) ───────────────────────────────────────────────

export interface DeviceCompareResult {
  device_model: string
  device_info: DeviceInfo
  stats: SummaryStats
  by_category: CategorySummary[]
}

// ── Filters ─────────────────────────────────────────────────────────────────

export interface Filters {
  device?: string
  model?: string
  category?: string
  backend?: string
  engine?: string
  status?: 'success' | 'error' | 'all'
  run_id?: string
  limit: number
  offset: number
}

// ── Response Validation (Phase 4a) ──────────────────────────────────────────

export type ValidationStatus = 'pass' | 'fail' | 'warn' | 'uncertain' | 'skip'

export interface ValidationSummary {
  total: number
  pass_count: number
  fail_count: number
  warn_count: number
  uncertain_count: number
  skip_count: number
  pass_rate: number
}

export interface CategoryValidation {
  category: string
  pass_count: number
  fail_count: number
  warn_count: number
  uncertain_count: number
  total: number
}

export interface ModelValidation {
  model_name: string
  pass_rate: number
  fail_rate: number
  truncation_rate: number
  total: number
}

// ── Quant Compare (Phase 6.1) ───────────────────────────────────────────────

export interface QuantPerformance {
  avg_decode_tps: number | null
  avg_latency_ms: number | null
  avg_ttft_ms: number | null
  avg_prefill_tps: number | null
  avg_output_tokens: number | null
}

export interface QuantQuality {
  total: number
  pass_count: number
  fail_count: number
  warn_count: number
  uncertain_count: number
  pass_rate: number
}

export interface QuantResource {
  avg_battery_delta: number | null
  avg_thermal_end_celsius: number | null
  avg_thermal_delta_celsius: number | null
  avg_system_pss_mb: number | null
}

export interface QuantComparisonItem {
  model_name: string
  quant_level: string
  result_count: number
  performance: QuantPerformance
  quality: QuantQuality
  resource: QuantResource
}

export interface QuantBaseline {
  baseline_quant: string
  quant_level: string
  tps_change_pct: number | null
  latency_change_pct: number | null
  pass_rate_change_pct: number | null
  battery_change_pct: number | null
}

export interface QuantComparisonGroup {
  base_model: string
  device: string | null
  quants: QuantComparisonItem[]
  deltas: QuantBaseline[]
  insight: string
}

export interface QuantComparisonResponse {
  groups: QuantComparisonGroup[]
}

export interface QuantSimilarityItem {
  prompt_id: string
  prompt_text: string
  category: string
  model_a: string
  model_b: string
  quant_a: string
  quant_b: string
  match_ratio: number
  a_length: number
  b_length: number
  validation_a: string | null
  validation_b: string | null
}

export interface QuantSimilaritySummary {
  category: string
  avg_match_ratio: number
  pair_count: number
}

export interface QuantSimilarityResponse {
  base_model: string
  pairs: QuantSimilarityItem[]
  by_category: QuantSimilaritySummary[]
  overall_avg_ratio: number
}