from __future__ import annotations

import logging
from typing import Optional

from db_adapter import DbAdapter, Row
from schemas import DeviceInfo, Metrics, ResourceProfile, ResultItem

logger = logging.getLogger(__name__)


# ── Query builder ─────────────────────────────────────────────────────────────

def _build_where(
    device: Optional[str],
    model: Optional[str],
    category: Optional[str],
    backend: Optional[str],
    status: Optional[str],
    run_id: Optional[str] = None,
    engine: Optional[str] = None,
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
    if engine:
        clauses.append("LOWER(m.engine) = LOWER(?)")
        params.append(engine)

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
        m.engine,
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
        r.battery_level_start,
        r.battery_level_end,
        r.thermal_start,
        r.thermal_end,
        r.voltage_start_mv,
        r.voltage_end_mv,
        r.current_before_ua,
        r.current_after_ua,
        r.system_pss_mb,
        r.profiling_error,
        ru.run_id           AS ci_run_id
    FROM results r
    JOIN devices d  ON r.device_id = d.id
    JOIN models  m  ON r.model_id  = m.id
    JOIN prompts p  ON r.prompt_id = p.id
    LEFT JOIN runs ru ON r.run_id  = ru.id
"""


def _safe_delta(a: Optional[int], b: Optional[int]) -> Optional[int]:
    """Compute b - a if both are non-None."""
    if a is not None and b is not None:
        return b - a
    return None


def _build_resource_profile(row: Row) -> Optional[ResourceProfile]:
    """Phase 6: DB row에서 ResourceProfile 빌드. 프로파일링 데이터 없으면 None."""
    bls = row["battery_level_start"]
    ble = row["battery_level_end"]
    ts = row["thermal_start"]
    te = row["thermal_end"]
    vs = row["voltage_start_mv"]
    ve = row["voltage_end_mv"]
    cb = row["current_before_ua"]
    ca = row["current_after_ua"]
    pss = row["system_pss_mb"]
    pe = row["profiling_error"]

    has_data = any(v is not None for v in (bls, ts, vs, pss, pe))
    if not has_data:
        return None

    return ResourceProfile(
        battery_level_start=bls,
        battery_level_end=ble,
        battery_delta=_safe_delta(bls, ble),
        thermal_start=ts,
        thermal_end=te,
        thermal_delta=_safe_delta(ts, te),
        thermal_start_celsius=round(ts / 10, 1) if ts is not None else None,
        thermal_end_celsius=round(te / 10, 1) if te is not None else None,
        voltage_start_mv=vs,
        voltage_end_mv=ve,
        voltage_delta_mv=_safe_delta(vs, ve),
        current_before_ua=cb,
        current_after_ua=ca,
        current_delta_ua=_safe_delta(cb, ca),
        system_pss_mb=pss,
        profiling_error=pe,
    )


def _row_to_item(row: Row) -> ResultItem:
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
        engine=row["engine"] or "mediapipe",
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
        resource_profile=_build_resource_profile(row),
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def load_all(
    db: DbAdapter,
    device: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    backend: Optional[str] = None,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    engine: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ResultItem], int]:
    where, params = _build_where(device, model, category, backend, status, run_id, engine)

    count_query = f"""
        SELECT COUNT(*) FROM results r
        JOIN devices d  ON r.device_id = d.id
        JOIN models  m  ON r.model_id  = m.id
        JOIN prompts p  ON r.prompt_id = p.id
        LEFT JOIN runs ru ON r.run_id  = ru.id
        {where}
    """
    row = await db.fetchone(count_query, tuple(params))
    total = row[0] if row else 0

    data_query = f"{_SELECT} {where} ORDER BY r.timestamp DESC LIMIT ? OFFSET ?"
    rows = await db.fetchall(data_query, tuple(params + [limit, offset]))

    return [_row_to_item(r) for r in rows], total


async def list_devices(db: DbAdapter) -> list[str]:
    rows = await db.fetchall("SELECT DISTINCT model FROM devices ORDER BY model")
    return [r[0] for r in rows if r[0]]


async def list_models(
    db: DbAdapter,
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

    rows = await db.fetchall(query, params)
    return [r[0] for r in rows if r[0]]


async def list_categories(db: DbAdapter) -> list[str]:
    rows = await db.fetchall(
        "SELECT DISTINCT category FROM prompts WHERE category != '' ORDER BY category"
    )
    return [r[0] for r in rows if r[0]]


async def list_runs(db: DbAdapter) -> list[str]:
    """Return distinct run_ids ordered by most recent first."""
    rows = await db.fetchall("SELECT run_id FROM runs ORDER BY id DESC")
    return [r[0] for r in rows if r[0]]


async def list_engines(db: DbAdapter) -> list[str]:
    """Return distinct engine values from models table."""
    rows = await db.fetchall(
        "SELECT DISTINCT engine FROM models WHERE engine != '' ORDER BY engine"
    )
    return [r[0] for r in rows if r[0]]
