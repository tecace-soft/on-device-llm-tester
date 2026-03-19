from __future__ import annotations

import logging
from typing import Optional

import aiosqlite

from schemas import DeviceInfo, Metrics, ResultItem

logger = logging.getLogger(__name__)


# ── Query builder ─────────────────────────────────────────────────────────────

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

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


_SELECT = """
    SELECT
        r.status,
        p.prompt_id         AS prompt_id,
        p.category          AS prompt_category,
        p.lang              AS prompt_lang,
        m.model_name,
        m.model_path,
        m.backend,
        d.manufacturer,
        d.model             AS device_model,
        d.product,
        d.soc,
        d.android_version,
        d.sdk_int,
        d.cpu_cores,
        d.max_heap_mb,
        p.prompt_text       AS prompt,
        r.response,
        r.latency_ms,
        r.init_time_ms,
        r.error,
        r.timestamp,
        r.ttft_ms,
        r.prefill_time_ms,
        r.decode_time_ms,
        r.input_token_count,
        r.output_token_count,
        r.prefill_tps,
        r.decode_tps,
        r.peak_java_memory_mb,
        r.peak_native_memory_mb,
        r.itl_p50_ms,
        r.itl_p95_ms,
        r.itl_p99_ms,
        ru.run_id           AS ci_run_id
    FROM results r
    JOIN devices d  ON r.device_id = d.id
    JOIN models  m  ON r.model_id  = m.id
    JOIN prompts p  ON r.prompt_id = p.id
    LEFT JOIN runs ru ON r.run_id  = ru.id
"""


def _row_to_item(row: aiosqlite.Row) -> ResultItem:
    has_metrics = row["status"] == "success" and row["ttft_ms"] is not None
    metrics = (
        Metrics(
            ttft_ms=row["ttft_ms"],
            prefill_time_ms=row["prefill_time_ms"],
            decode_time_ms=row["decode_time_ms"],
            input_token_count=row["input_token_count"],
            output_token_count=row["output_token_count"],
            prefill_tps=row["prefill_tps"],
            decode_tps=row["decode_tps"],
            peak_java_memory_mb=row["peak_java_memory_mb"],
            peak_native_memory_mb=row["peak_native_memory_mb"],
            itl_p50_ms=row["itl_p50_ms"],
            itl_p95_ms=row["itl_p95_ms"],
            itl_p99_ms=row["itl_p99_ms"],
        )
        if has_metrics
        else None
    )

    return ResultItem(
        status=row["status"],
        prompt_id=row["prompt_id"] or "",
        prompt_category=row["prompt_category"] or "",
        prompt_lang=row["prompt_lang"] or "",
        model_name=row["model_name"] or "",
        model_path=row["model_path"] or "",
        backend=row["backend"] or "",
        device=DeviceInfo(
            manufacturer=row["manufacturer"] or "",
            model=row["device_model"] or "",
            product=row["product"] or "",
            soc=row["soc"] or "",
            android_version=row["android_version"] or "",
            sdk_int=row["sdk_int"] or 0,
            cpu_cores=row["cpu_cores"] or 0,
            max_heap_mb=row["max_heap_mb"] or 0,
        ),
        prompt=row["prompt"] or "",
        response=row["response"] or "",
        latency_ms=row["latency_ms"],
        init_time_ms=row["init_time_ms"],
        metrics=metrics,
        error=row["error"],
        timestamp=row["timestamp"],
        run_id=row["ci_run_id"],
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def load_all(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    backend: Optional[str] = None,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ResultItem], int]:
    where, params = _build_where(device, model, category, backend, status, run_id)

    count_query = f"""
        SELECT COUNT(*) FROM results r
        JOIN devices d  ON r.device_id = d.id
        JOIN models  m  ON r.model_id  = m.id
        JOIN prompts p  ON r.prompt_id = p.id
        LEFT JOIN runs ru ON r.run_id  = ru.id
        {where}
    """
    async with db.execute(count_query, params) as cur:
        row = await cur.fetchone()
        total = row[0] if row else 0

    data_query = f"{_SELECT} {where} ORDER BY r.timestamp DESC LIMIT ? OFFSET ?"
    async with db.execute(data_query, params + [limit, offset]) as cur:
        rows = await cur.fetchall()

    return [_row_to_item(r) for r in rows], total


async def list_devices(db: aiosqlite.Connection) -> list[str]:
    async with db.execute("SELECT DISTINCT model FROM devices ORDER BY model") as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows if r[0]]


async def list_models(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
) -> list[str]:
    if device:
        query = """
            SELECT DISTINCT m.model_name
            FROM models m
            JOIN results r ON r.model_id = m.id
            JOIN devices d ON r.device_id = d.id
            WHERE d.model = ?
            ORDER BY m.model_name
        """
        params: tuple = (device,)
    else:
        query = "SELECT DISTINCT model_name FROM models ORDER BY model_name"
        params = ()

    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows if r[0]]


async def list_categories(db: aiosqlite.Connection) -> list[str]:
    async with db.execute(
        "SELECT DISTINCT category FROM prompts WHERE category != '' ORDER BY category"
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows if r[0]]


async def list_runs(db: aiosqlite.Connection) -> list[str]:
    """Return distinct run_ids ordered by most recent first."""
    async with db.execute(
        "SELECT run_id FROM runs ORDER BY id DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows if r[0]]