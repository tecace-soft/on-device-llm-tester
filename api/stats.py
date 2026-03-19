from __future__ import annotations

from typing import Optional

import aiosqlite

from schemas import CategorySummary, CompareResult, ModelSummary, PercentileStats, SummaryStats


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
        by_cat = await compute_by_category(db, device=device, model=name, backend=backend)
        results.append(CompareResult(model_name=name, stats=stats, by_category=by_cat))
    return results