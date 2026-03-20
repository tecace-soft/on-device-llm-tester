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


class ResultItem(BaseModel):
    status: str
    prompt_id: str = ""
    prompt_category: str = ""
    prompt_lang: str = ""
    model_name: str = ""
    model_path: str = ""
    backend: str = ""
    device: DeviceInfo = DeviceInfo()
    prompt: str = ""
    response: str = ""
    latency_ms: Optional[float] = None
    init_time_ms: Optional[float] = None
    metrics: Optional[Metrics] = None
    error: Optional[str] = None
    timestamp: Optional[Any] = None
    run_id: Optional[str] = None


# ── Summary / aggregate shapes ─────────────────────────────────────────────────

class PercentileStats(BaseModel):
    p50: float
    p95: float
    p99: float
    avg: float
    min: float
    max: float


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