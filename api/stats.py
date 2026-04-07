from __future__ import annotations

from typing import Optional

import aiosqlite

from schemas import (
    CategorySummary,
    CategoryValidation,
    CompareResult,
    DeviceCompareResult,
    ModelSummary,
    ModelValidation,
    PercentileStats,
    ResourceSummary,
    SummaryStats,
    ValidationSummary,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_where(
    device: Optional[str],
    model: Optional[str],
    category: Optional[str],
    backend: Optional[str],
    status: Optional[str],
    run_id: Optional[str] = None,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []

    if device:
        clauses.append("d.model = ?")
        params.append(device)
    if model:
        clauses.append("m.model_name = ?")
        params.append(model)
    if category:
        clauses.append("p.category = ?")
        params.append(category)
    if backend:
        clauses.append("UPPER(m.backend) = UPPER(?)")
        params.append(backend)
    if status and status != "all":
        clauses.append("r.status = ?")
        params.append(status)
    if run_id:
        clauses.append("ru.run_id = ?")
        params.append(run_id)

    where = ("AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


_JOINS = """
    FROM results r
    JOIN devices d  ON r.device_id = d.id
    JOIN models  m  ON r.model_id  = m.id
    JOIN prompts p  ON r.prompt_id = p.id
    LEFT JOIN runs ru ON r.run_id  = ru.id
    WHERE 1=1
"""

_SUMMARY_SELECT = """
    SELECT
        COUNT(*)                                              AS total,
        SUM(CASE WHEN r.status='success' THEN 1 ELSE 0 END)  AS success,
        SUM(CASE WHEN r.status='error'   THEN 1 ELSE 0 END)  AS errors,
        AVG(CASE WHEN r.status='success' THEN r.latency_ms  END) AS avg_latency,
        MIN(CASE WHEN r.status='success' THEN r.latency_ms  END) AS min_latency,
        MAX(CASE WHEN r.status='success' THEN r.latency_ms  END) AS max_latency,
        AVG(r.ttft_ms)                AS avg_ttft_ms,
        AVG(r.decode_tps)             AS avg_decode_tps,
        AVG(r.prefill_tps)            AS avg_prefill_tps,
        AVG(r.init_time_ms)           AS avg_init_time_ms,
        AVG(r.peak_native_memory_mb)  AS avg_peak_native_mem_mb,
        AVG(r.peak_java_memory_mb)    AS avg_peak_java_mem_mb,
        AVG(r.output_token_count)     AS avg_output_tokens
"""


async def _percentile(
    db: aiosqlite.Connection,
    pct: float,
    where: str,
    params: list,
) -> Optional[float]:
    count_q = f"SELECT COUNT(*) {_JOINS} {where} AND r.status='success' AND r.latency_ms IS NOT NULL"
    async with db.execute(count_q, params) as cur:
        row = await cur.fetchone()
        n = row[0] if row else 0

    if n == 0:
        return None

    offset = max(0, int(n * pct) - 1)
    val_q = f"""
        SELECT r.latency_ms {_JOINS} {where}
        AND r.status='success' AND r.latency_ms IS NOT NULL
        ORDER BY r.latency_ms
        LIMIT 1 OFFSET ?
    """
    async with db.execute(val_q, params + [offset]) as cur:
        row = await cur.fetchone()
        return row[0] if row else None


async def _build_resource_summary(
    db: aiosqlite.Connection,
    where: str,
    params: list,
    total: int,
) -> Optional[ResourceSummary]:
    """Phase 6: 리소스 프로파일링 집계 통계."""
    q = f"""
        SELECT
            COUNT(r.battery_level_start) AS profiled,
            AVG(r.thermal_end - r.thermal_start) AS avg_thermal_delta,
            AVG(r.voltage_end_mv - r.voltage_start_mv) AS avg_voltage_delta,
            AVG(r.current_after_ua - r.current_before_ua) AS avg_current_delta,
            AVG(r.system_pss_mb) AS avg_pss
        {_JOINS}
        {where}
        AND r.battery_level_start IS NOT NULL
    """
    async with db.execute(q, params) as cur:
        row = await cur.fetchone()

    profiled = row["profiled"] or 0
    if profiled == 0:
        return None

    return ResourceSummary(
        avg_thermal_delta_celsius=round(row["avg_thermal_delta"] / 10, 2) if row["avg_thermal_delta"] is not None else None,
        avg_voltage_delta_mv=round(row["avg_voltage_delta"], 1) if row["avg_voltage_delta"] is not None else None,
        avg_current_delta_ua=round(row["avg_current_delta"], 0) if row["avg_current_delta"] is not None else None,
        avg_system_pss_mb=round(row["avg_pss"], 1) if row["avg_pss"] is not None else None,
        profiling_coverage=round(profiled / total * 100, 1) if total > 0 else 0.0,
    )


async def _build_summary(
    db: aiosqlite.Connection,
    where: str,
    params: list,
) -> SummaryStats:
    q = f"{_SUMMARY_SELECT} {_JOINS} {where}"
    async with db.execute(q, params) as cur:
        r = await cur.fetchone()

    total = r["total"] or 0
    success = r["success"] or 0
    errors = r["errors"] or 0

    latency_stats: Optional[PercentileStats] = None
    if success > 0 and r["avg_latency"] is not None:
        p50 = await _percentile(db, 0.50, where, params)
        p95 = await _percentile(db, 0.95, where, params)
        p99 = await _percentile(db, 0.99, where, params)
        latency_stats = PercentileStats(
            p50=p50 or 0.0,
            p95=p95 or 0.0,
            p99=p99 or 0.0,
            avg=r["avg_latency"] or 0.0,
            min=r["min_latency"] or 0.0,
            max=r["max_latency"] or 0.0,
        )

    resource = await _build_resource_summary(db, where, params, total)

    return SummaryStats(
        total=total,
        success=success,
        errors=errors,
        success_rate=round(success / total * 100, 1) if total else 0.0,
        latency=latency_stats,
        avg_ttft_ms=r["avg_ttft_ms"],
        avg_decode_tps=r["avg_decode_tps"],
        avg_prefill_tps=r["avg_prefill_tps"],
        avg_init_time_ms=r["avg_init_time_ms"],
        avg_peak_native_mem_mb=r["avg_peak_native_mem_mb"],
        avg_peak_java_mem_mb=r["avg_peak_java_mem_mb"],
        avg_output_tokens=r["avg_output_tokens"],
        resource=resource,
    )


# ── Public API ────────────────────────────────────────────────────────────────


async def compute_summary(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    backend: Optional[str] = None,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
) -> SummaryStats:
    where, params = _build_where(device, model, category, backend, status, run_id)
    return await _build_summary(db, where, params)


async def compute_by_model(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    category: Optional[str] = None,
    backend: Optional[str] = None,
) -> list[ModelSummary]:
    where, params = _build_where(device, None, category, backend, None)
    q = f"SELECT DISTINCT m.model_name {_JOINS} {where} ORDER BY m.model_name"
    async with db.execute(q, params) as cur:
        model_rows = await cur.fetchall()

    results = []
    for row in model_rows:
        model_name = row[0]
        m_where, m_params = _build_where(device, model_name, category, backend, None)
        stats = await _build_summary(db, m_where, m_params)
        results.append(ModelSummary(model_name=model_name, stats=stats))
    return results


async def compute_by_category(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    model: Optional[str] = None,
    backend: Optional[str] = None,
) -> list[CategorySummary]:
    where, params = _build_where(device, model, None, backend, None)
    q = f"SELECT DISTINCT p.category {_JOINS} {where} AND p.category != '' ORDER BY p.category"
    async with db.execute(q, params) as cur:
        cat_rows = await cur.fetchall()

    results = []
    for row in cat_rows:
        cat = row[0]
        c_where, c_params = _build_where(device, model, cat, backend, None)
        stats = await _build_summary(db, c_where, c_params)
        results.append(CategorySummary(category=cat, stats=stats))
    return results


async def compute_compare(
    db: aiosqlite.Connection,
    model_names: list[str],
    device: Optional[str] = None,
    backend: Optional[str] = None,
) -> list[CompareResult]:
    results = []
    for name in model_names:
        where, params = _build_where(device, name, None, backend, None)
        stats = await _build_summary(db, where, params)
        by_cat = await compute_by_category(
            db, device=device, model=name, backend=backend
        )
        results.append(CompareResult(model_name=name, stats=stats, by_category=by_cat))
    return results


# ── Device Compare (Phase 3) ─────────────────────────────────────────────────


async def compute_compare_devices(
    db: aiosqlite.Connection,
    device_models: list[str],
    model: Optional[str] = None,
    backend: Optional[str] = None,
) -> list[DeviceCompareResult]:
    """디바이스 간 동일 모델 성능 비교."""
    results = []
    for device_model in device_models:
        where, params = _build_where(device_model, model, None, backend, None)
        stats = await _build_summary(db, where, params)

        device_info: dict = {}
        async with db.execute(
            "SELECT manufacturer, model, product, soc, android_version, sdk_int, cpu_cores, max_heap_mb FROM devices WHERE model = ?",
            (device_model,),
        ) as cur:
            dev_row = await cur.fetchone()
            if dev_row:
                device_info = {
                    "manufacturer": dev_row["manufacturer"],
                    "model": dev_row["model"],
                    "product": dev_row["product"],
                    "soc": dev_row["soc"],
                    "android_version": dev_row["android_version"],
                    "sdk_int": dev_row["sdk_int"],
                    "cpu_cores": dev_row["cpu_cores"],
                    "max_heap_mb": dev_row["max_heap_mb"],
                }

        by_cat = await compute_by_category(
            db, device=device_model, model=model, backend=backend
        )

        results.append(
            DeviceCompareResult(
                device_model=device_model,
                device_info=device_info,
                stats=stats,
                by_category=by_cat,
            )
        )
    return results


# ── Response Validation stats (Phase 4a) ──────────────────────────────────────


async def compute_validation_summary(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    model: Optional[str] = None,
    run_id: Optional[str] = None,
) -> ValidationSummary:
    where, params = _build_where(device, model, None, None, None, run_id=run_id)

    q = f"""
        SELECT
            COUNT(*)                                                         AS total,
            SUM(CASE WHEN r.validation_status = 'pass'      THEN 1 ELSE 0 END) AS v_pass,
            SUM(CASE WHEN r.validation_status = 'fail'      THEN 1 ELSE 0 END) AS v_fail,
            SUM(CASE WHEN r.validation_status = 'warn'      THEN 1 ELSE 0 END) AS v_warn,
            SUM(CASE WHEN r.validation_status = 'uncertain' THEN 1 ELSE 0 END) AS v_uncertain,
            SUM(CASE WHEN r.validation_status = 'skip'      THEN 1 ELSE 0 END) AS v_skip
        {_JOINS}
        {where}
    """
    async with db.execute(q, params) as cur:
        row = await cur.fetchone()

    total = row["total"] or 0
    v_pass = row["v_pass"] or 0
    v_skip = row["v_skip"] or 0
    evaluable = total - v_skip

    return ValidationSummary(
        total=total,
        pass_count=v_pass,
        fail_count=row["v_fail"] or 0,
        warn_count=row["v_warn"] or 0,
        uncertain_count=row["v_uncertain"] or 0,
        skip_count=v_skip,
        pass_rate=round(v_pass / evaluable, 4) if evaluable > 0 else 0.0,
    )


async def compute_validation_by_category(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    model: Optional[str] = None,
) -> list[CategoryValidation]:
    where, params = _build_where(device, model, None, None, None)

    q = f"""
        SELECT
            p.category,
            COUNT(*)                                                         AS total,
            SUM(CASE WHEN r.validation_status = 'pass'      THEN 1 ELSE 0 END) AS v_pass,
            SUM(CASE WHEN r.validation_status = 'fail'      THEN 1 ELSE 0 END) AS v_fail,
            SUM(CASE WHEN r.validation_status = 'warn'      THEN 1 ELSE 0 END) AS v_warn,
            SUM(CASE WHEN r.validation_status = 'uncertain' THEN 1 ELSE 0 END) AS v_uncertain
        {_JOINS}
        {where} AND p.category != ''
        GROUP BY p.category
        ORDER BY p.category
    """
    async with db.execute(q, params) as cur:
        rows = await cur.fetchall()

    return [
        CategoryValidation(
            category=row["category"],
            pass_count=row["v_pass"] or 0,
            fail_count=row["v_fail"] or 0,
            warn_count=row["v_warn"] or 0,
            uncertain_count=row["v_uncertain"] or 0,
            total=row["total"] or 0,
        )
        for row in rows
    ]


async def compute_validation_by_model(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
) -> list[ModelValidation]:
    where, params = _build_where(device, None, None, None, None)

    q = f"""
        SELECT
            m.model_name,
            COUNT(*)                                                         AS total,
            SUM(CASE WHEN r.validation_status = 'pass'      THEN 1 ELSE 0 END) AS v_pass,
            SUM(CASE WHEN r.validation_status = 'fail'      THEN 1 ELSE 0 END) AS v_fail,
            SUM(CASE WHEN r.validation_status = 'skip'      THEN 1 ELSE 0 END) AS v_skip,
            SUM(CASE WHEN json_extract(r.validation_detail, '$.checks.truncated') = 1 THEN 1 ELSE 0 END) AS truncated
        {_JOINS}
        {where}
        GROUP BY m.model_name
        ORDER BY m.model_name
    """
    async with db.execute(q, params) as cur:
        rows = await cur.fetchall()

    results = []
    for row in rows:
        total = row["total"] or 0
        evaluable = total - (row["v_skip"] or 0)
        results.append(
            ModelValidation(
                model_name=row["model_name"],
                pass_rate=(
                    round((row["v_pass"] or 0) / evaluable, 4) if evaluable > 0 else 0.0
                ),
                fail_rate=(
                    round((row["v_fail"] or 0) / evaluable, 4) if evaluable > 0 else 0.0
                ),
                truncation_rate=(
                    round((row["truncated"] or 0) / total, 4) if total > 0 else 0.0
                ),
                total=total,
            )
        )
    return results