from __future__ import annotations

from typing import Any, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool


class ApiSuccess(BaseModel, Generic[T]):
    status: Literal["ok"] = "ok"
    data: T
    meta: Optional[PaginationMeta] = None


class ApiError(BaseModel):
    status: Literal["error"] = "error"
    error: str
    detail: Optional[str] = None


# ── Result shapes ──────────────────────────────────────────────────────────────

class DeviceInfo(BaseModel):
    manufacturer: str = ""
    model: str = ""
    product: str = ""
    soc: str = ""
    android_version: str = ""
    sdk_int: int = 0
    cpu_cores: int = 0
    max_heap_mb: int = 0


class Metrics(BaseModel):
    ttft_ms: Optional[float] = None
    prefill_time_ms: Optional[float] = None
    decode_time_ms: Optional[float] = None
    input_token_count: Optional[int] = None
    output_token_count: Optional[int] = None
    prefill_tps: Optional[float] = None
    decode_tps: Optional[float] = None
    peak_java_memory_mb: Optional[float] = None
    peak_native_memory_mb: Optional[float] = None
    itl_p50_ms: Optional[float] = None
    itl_p95_ms: Optional[float] = None
    itl_p99_ms: Optional[float] = None


# ── Phase 6: Resource Profile ─────────────────────────────────────────────────

class ResourceProfile(BaseModel):
    battery_level_start: Optional[int] = None
    battery_level_end: Optional[int] = None
    battery_delta: Optional[int] = None
    thermal_start: Optional[int] = None
    thermal_end: Optional[int] = None
    thermal_delta: Optional[int] = None
    thermal_start_celsius: Optional[float] = None
    thermal_end_celsius: Optional[float] = None
    voltage_start_mv: Optional[int] = None
    voltage_end_mv: Optional[int] = None
    voltage_delta_mv: Optional[int] = None
    current_before_ua: Optional[int] = None
    current_after_ua: Optional[int] = None
    current_delta_ua: Optional[int] = None
    system_pss_mb: Optional[float] = None
    profiling_error: Optional[str] = None


class ResultItem(BaseModel):
    status: str
    prompt_id: str = ""
    prompt_category: str = ""
    prompt_lang: str = ""
    model_name: str = ""
    model_path: str = ""
    backend: str = ""
    engine: str = "mediapipe"
    device: DeviceInfo = DeviceInfo()
    prompt: str = ""
    response: str = ""
    latency_ms: Optional[float] = None
    init_time_ms: Optional[float] = None
    metrics: Optional[Metrics] = None
    error: Optional[str] = None
    timestamp: Optional[Any] = None
    run_id: Optional[str] = None
    resource_profile: Optional[ResourceProfile] = None


# ── Summary / aggregate shapes ─────────────────────────────────────────────────

class PercentileStats(BaseModel):
    p50: float
    p95: float
    p99: float
    avg: float
    min: float
    max: float


# ── Phase 6: Resource Summary ─────────────────────────────────────────────────

class ResourceSummary(BaseModel):
    avg_thermal_delta_celsius: Optional[float] = None
    avg_voltage_delta_mv: Optional[float] = None
    avg_current_delta_ua: Optional[float] = None
    avg_system_pss_mb: Optional[float] = None
    profiling_coverage: Optional[float] = None


class SummaryStats(BaseModel):
    total: int
    success: int
    errors: int
    success_rate: float
    latency: Optional[PercentileStats] = None
    avg_ttft_ms: Optional[float] = None
    avg_decode_tps: Optional[float] = None
    avg_prefill_tps: Optional[float] = None
    avg_init_time_ms: Optional[float] = None
    avg_peak_native_mem_mb: Optional[float] = None
    avg_peak_java_mem_mb: Optional[float] = None
    avg_output_tokens: Optional[float] = None
    resource: Optional[ResourceSummary] = None


class ModelSummary(BaseModel):
    model_name: str
    stats: SummaryStats


class CategorySummary(BaseModel):
    category: str
    stats: SummaryStats


class CompareResult(BaseModel):
    model_name: str
    stats: SummaryStats
    by_category: List[CategorySummary]


# ── CI/CD Run shapes (Phase 2) ─────────────────────────────────────────────────

class RunItem(BaseModel):
    id: int
    run_id: str
    trigger: str
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str
    result_count: Optional[int] = None


# ── Device Compare shapes (Phase 3) ────────────────────────────────────────────

class DeviceCompareResult(BaseModel):
    device_model: str
    device_info: dict
    stats: SummaryStats
    by_category: List[CategorySummary]

# ── Response Validation shapes (Phase 4a) ───────────────────────────────────

class ValidationSummary(BaseModel):
    total: int
    pass_count: int
    fail_count: int
    warn_count: int
    uncertain_count: int
    skip_count: int
    pass_rate: float


class CategoryValidation(BaseModel):
    category: str
    pass_count: int
    fail_count: int
    warn_count: int
    uncertain_count: int
    total: int


class ModelValidation(BaseModel):
    model_name: str
    pass_rate: float
    fail_rate: float
    truncation_rate: float
    total: int