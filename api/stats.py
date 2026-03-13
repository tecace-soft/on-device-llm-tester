from __future__ import annotations

from typing import Dict, List, Optional

from schemas import CategorySummary, CompareResult, ModelSummary, PercentileStats, ResultItem, SummaryStats


def _pct(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(p / 100.0 * (len(sorted_vals) - 1))
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def _avg(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _safe(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def compute_summary(rows: List[ResultItem]) -> SummaryStats:
    total = len(rows)
    success_rows = [r for r in rows if r.status == "success"]
    success = len(success_rows)
    errors = total - success

    latency_vals = sorted(
        v for r in success_rows
        if (v := _safe(r.latency_ms)) is not None
    )

    def metric_vals(key: str) -> List[float]:
        out = []
        for r in success_rows:
            if r.metrics:
                v = _safe(getattr(r.metrics, key, None))
                if v is not None:
                    out.append(v)
        return out

    latency_stats = None
    if latency_vals:
        latency_stats = PercentileStats(
            p50=_pct(latency_vals, 50),
            p95=_pct(latency_vals, 95),
            p99=_pct(latency_vals, 99),
            avg=sum(latency_vals) / len(latency_vals),
            min=latency_vals[0],
            max=latency_vals[-1],
        )

    init_vals = [v for r in success_rows if (v := _safe(r.init_time_ms)) is not None]

    return SummaryStats(
        total=total,
        success=success,
        errors=errors,
        success_rate=round(success / total * 100, 1) if total else 0.0,
        latency=latency_stats,
        avg_ttft_ms=_avg(metric_vals("ttft_ms")),
        avg_decode_tps=_avg(metric_vals("decode_tps")),
        avg_prefill_tps=_avg(metric_vals("prefill_tps")),
        avg_init_time_ms=_avg(init_vals),
        avg_peak_native_mem_mb=_avg(metric_vals("peak_native_memory_mb")),
        avg_peak_java_mem_mb=_avg(metric_vals("peak_java_memory_mb")),
        avg_output_tokens=_avg(metric_vals("output_token_count")),
    )


def compute_by_model(rows: List[ResultItem]) -> List[ModelSummary]:
    groups: Dict[str, List[ResultItem]] = {}
    for r in rows:
        groups.setdefault(r.model_name, []).append(r)
    return [ModelSummary(model_name=k, stats=compute_summary(v)) for k, v in sorted(groups.items())]


def compute_by_category(rows: List[ResultItem]) -> List[CategorySummary]:
    groups: Dict[str, List[ResultItem]] = {}
    for r in rows:
        groups.setdefault(r.prompt_category or "unknown", []).append(r)
    return [CategorySummary(category=k, stats=compute_summary(v)) for k, v in sorted(groups.items())]


def compute_compare(rows: List[ResultItem], model_names: List[str]) -> List[CompareResult]:
    results = []
    for name in model_names:
        model_rows = [r for r in rows if r.model_name == name]
        results.append(CompareResult(
            model_name=name,
            stats=compute_summary(model_rows),
            by_category=compute_by_category(model_rows),
        ))
    return results
