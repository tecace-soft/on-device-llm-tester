import csv
import io
import logging
import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from cache import invalidate_cache
from db import lifespan
from db_adapter import DbAdapter
from loader import list_categories, list_devices, list_engines, list_models, list_runs, load_all

from schemas import (
    ApiError,
    ApiSuccess,
    CategorySummary,
    CategoryValidation,
    CompareResult,
    DeviceCompareResult,
    ModelSummary,
    ModelValidation,
    PaginationMeta,
    QuantComparisonResponse,
    QuantDiffItem,
    QuantSimilarityResponse,
    ResultItem,
    RunItem,
    SummaryStats,
    ValidationSummary,
)

from stats import (
    compute_by_category,
    compute_by_model,
    compute_compare,
    compute_compare_devices,
    compute_quant_comparison,
    compute_quant_diff,
    compute_quant_similarity,
    compute_summary,
    compute_validation_summary,
    compute_validation_by_category,
    compute_validation_by_model,
)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="On-Device LLM Tester API",
    description="Benchmark results API for on-device LLM inference",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth middleware ────────────────────────────────────────────────────────────


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/api"):
        key = request.headers.get("x-api-key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse(
                status_code=401,
                content=ApiError(error="Invalid API key").model_dump(),
            )
    return await call_next(request)


# ── Exception handler ─────────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ApiError(error="Internal server error", detail=str(exc)).model_dump(),
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _db(request: Request) -> DbAdapter:
    return DbAdapter(request.app.state.db, request.app.state.db_mode)


# ── /auth ─────────────────────────────────────────────────────────────────────


@app.post("/auth/login")
async def auth_login(request: Request):
    """Dashboard password gate — validates against DASHBOARD_PASSWORD env var.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §9
    Used by: dashboard Login page
    Why server-side: keeps the password out of the JS bundle entirely.
    If DASHBOARD_PASSWORD is unset, any submission is accepted (open access).
    """
    body = await request.json()
    password: str = body.get("password", "")
    expected: str = os.getenv("DASHBOARD_PASSWORD", "")
    if not expected or password == expected:
        return {"ok": True}
    return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid password"})


# ── /health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health(request: Request):
    """Render health check + DB 연결 상태 확인.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §7.4
    Used by: Render health check, UptimeRobot 모니터링
    """
    adapter = _db(request)
    try:
        await adapter.fetchone("SELECT 1")
        return {"status": "ok", "db_mode": request.app.state.db_mode}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(e)},
        )


# ── /api/cache ────────────────────────────────────────────────────────────────


@app.post("/api/cache/invalidate")
async def cache_invalidate():
    """집계 쿼리 캐시 전체 무효화.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §8.4
    Used by: CI ingest 완료 후 수동 호출, 관리용
    Note: /api/* 경로이므로 API_KEY 설정 시 auth_middleware가 자동 보호.
    """
    cleared = invalidate_cache()
    return {"status": "ok", "cleared": cleared}


# ── /api/results ──────────────────────────────────────────────────────────────


@app.get("/api/results", response_model=ApiSuccess[List[ResultItem]])
async def get_results(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="success | error | all"),
    run_id: Optional[str] = Query(None, description="Filter by CI run_id"),
    engine: Optional[str] = Query(None, description="Filter by engine: mediapipe | llamacpp"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows, total = await load_all(
        _db(request),
        device=device,
        model=model,
        category=category,
        backend=backend,
        status=status if status != "all" else None,
        run_id=run_id,
        engine=engine,
        limit=limit,
        offset=offset,
    )
    return ApiSuccess(
        data=rows,
        meta=PaginationMeta(
            total=total, limit=limit, offset=offset, has_more=offset + limit < total
        ),
    )


@app.get("/api/results/summary", response_model=ApiSuccess[SummaryStats])
async def get_summary(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    stats = await compute_summary(
        _db(request),
        device=device,
        model=model,
        category=category,
        backend=backend,
        status=status if status != "all" else None,
    )
    return ApiSuccess(data=stats)


@app.get("/api/results/by-model", response_model=ApiSuccess[List[ModelSummary]])
async def get_by_model(
    request: Request,
    device: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    data = await compute_by_model(
        _db(request), device=device, category=category, backend=backend
    )
    return ApiSuccess(data=data)


@app.get("/api/results/by-category", response_model=ApiSuccess[List[CategorySummary]])
async def get_by_category(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    data = await compute_by_category(
        _db(request), device=device, model=model, backend=backend
    )
    return ApiSuccess(data=data)


@app.get("/api/results/compare", response_model=ApiSuccess[List[CompareResult]])
async def get_compare(
    request: Request,
    models: str = Query(..., description="Comma-separated model names"),
    device: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    model_names = [m.strip() for m in models.split(",") if m.strip()]
    if len(model_names) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 model names")
    data = await compute_compare(
        _db(request), model_names=model_names, device=device, backend=backend
    )
    return ApiSuccess(data=data)


# ── /api/results/compare-devices (Phase 3) ────────────────────────────────────


@app.get(
    "/api/results/compare-devices", response_model=ApiSuccess[List[DeviceCompareResult]]
)
async def get_compare_devices(
    request: Request,
    devices: str = Query(
        ..., description="Comma-separated device model names (e.g. SM-S931U,SM-S926U)"
    ),
    model: Optional[str] = Query(
        None, description="Model name to compare across devices"
    ),
    backend: Optional[str] = Query(None),
):
    device_models = [d.strip() for d in devices.split(",") if d.strip()]
    if len(device_models) < 2:
        raise HTTPException(
            status_code=400, detail="Provide at least 2 device model names"
        )
    data = await compute_compare_devices(
        _db(request),
        device_models=device_models,
        model=model,
        backend=backend,
    )
    return ApiSuccess(data=data)


# ── /api/runs ──────────────────────────────────────────────────────────────────


@app.get("/api/runs", response_model=ApiSuccess[List[RunItem]])
async def get_runs(
    request: Request,
    status: Optional[str] = Query(None, description="success | error | running | all"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    adapter = _db(request)

    clauses: list[str] = []
    params: list = []
    if status and status != "all":
        clauses.append("r.status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    row = await adapter.fetchone(f"SELECT COUNT(*) FROM runs r {where}", tuple(params))
    total = row[0] if row else 0

    query = f"""
        SELECT
            r.id, r.run_id, r.trigger, r.commit_sha, r.branch,
            r.started_at, r.finished_at, r.status,
            COUNT(res.id) AS result_count
        FROM runs r
        LEFT JOIN results res ON res.run_id = r.id
        {where}
        GROUP BY r.id
        ORDER BY r.id DESC
        LIMIT ? OFFSET ?
    """
    rows = await adapter.fetchall(query, tuple(params + [limit, offset]))

    items = [
        RunItem(
            id=row["id"],
            run_id=row["run_id"],
            trigger=row["trigger"],
            commit_sha=row["commit_sha"],
            branch=row["branch"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            result_count=row["result_count"],
        )
        for row in rows
    ]
    return ApiSuccess(
        data=items,
        meta=PaginationMeta(
            total=total, limit=limit, offset=offset, has_more=offset + limit < total
        ),
    )


@app.get("/api/runs/{run_id}", response_model=ApiSuccess[RunItem])
async def get_run(request: Request, run_id: str):
    adapter = _db(request)
    row = await adapter.fetchone(
        """
        SELECT
            r.id, r.run_id, r.trigger, r.commit_sha, r.branch,
            r.started_at, r.finished_at, r.status,
            COUNT(res.id) AS result_count
        FROM runs r
        LEFT JOIN results res ON res.run_id = r.id
        WHERE r.run_id = ?
        GROUP BY r.id
    """,
        (run_id,),
    )

    if not row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return ApiSuccess(
        data=RunItem(
            id=row["id"],
            run_id=row["run_id"],
            trigger=row["trigger"],
            commit_sha=row["commit_sha"],
            branch=row["branch"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            result_count=row["result_count"],
        )
    )


@app.get("/api/runs/{run_id}/summary", response_model=ApiSuccess[SummaryStats])
async def get_run_summary(request: Request, run_id: str):
    adapter = _db(request)

    row = await adapter.fetchone("SELECT id FROM runs WHERE run_id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    stats = await compute_summary(adapter, run_id=run_id)
    return ApiSuccess(data=stats)


# ── /api/models, /api/devices, /api/categories, /api/engines, /api/runs-list ──


@app.get("/api/models", response_model=ApiSuccess[List[str]])
async def get_models(request: Request, device: Optional[str] = Query(None)):
    return ApiSuccess(data=await list_models(_db(request), device=device))


@app.get("/api/devices", response_model=ApiSuccess[List[str]])
async def get_devices(request: Request):
    return ApiSuccess(data=await list_devices(_db(request)))


@app.get("/api/categories", response_model=ApiSuccess[List[str]])
async def get_categories(request: Request):
    return ApiSuccess(data=await list_categories(_db(request)))


@app.get("/api/engines", response_model=ApiSuccess[List[str]])
async def get_engines(request: Request):
    """List distinct engine types (e.g. mediapipe, llamacpp)."""
    return ApiSuccess(data=await list_engines(_db(request)))


@app.get("/api/run-ids", response_model=ApiSuccess[List[str]])
async def get_run_ids(request: Request):
    """Lightweight list of run_ids for filter dropdowns."""
    return ApiSuccess(data=await list_runs(_db(request)))


# ── /api/export/csv ───────────────────────────────────────────────────────────


@app.get("/api/export/csv")
async def export_csv(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    engine: Optional[str] = Query(None),
):
    rows, total = await load_all(
        _db(request),
        device=device,
        model=model,
        category=category,
        backend=backend,
        status=status if status != "all" else None,
        run_id=run_id,
        engine=engine,
        limit=10_000,
        offset=0,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data matching filters")

    fieldnames = [
        "status",
        "prompt_id",
        "prompt_category",
        "prompt_lang",
        "model_name",
        "backend",
        "engine",
        "device_manufacturer",
        "device_model",
        "device_soc",
        "android_version",
        "prompt",
        "response",
        "latency_ms",
        "init_time_ms",
        "ttft_ms",
        "prefill_time_ms",
        "decode_time_ms",
        "input_token_count",
        "output_token_count",
        "prefill_tps",
        "decode_tps",
        "peak_java_memory_mb",
        "peak_native_memory_mb",
        "itl_p50_ms",
        "itl_p95_ms",
        "itl_p99_ms",
        "timestamp",
        "run_id",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(
            {
                "status": r.status,
                "prompt_id": r.prompt_id,
                "prompt_category": r.prompt_category,
                "prompt_lang": r.prompt_lang,
                "model_name": r.model_name,
                "backend": r.backend,
                "engine": r.engine,
                "device_manufacturer": r.device.manufacturer,
                "device_model": r.device.model,
                "device_soc": r.device.soc,
                "android_version": r.device.android_version,
                "prompt": r.prompt,
                "response": r.response,
                "latency_ms": r.latency_ms,
                "init_time_ms": r.init_time_ms,
                "ttft_ms": r.metrics.ttft_ms if r.metrics else None,
                "prefill_time_ms": r.metrics.prefill_time_ms if r.metrics else None,
                "decode_time_ms": r.metrics.decode_time_ms if r.metrics else None,
                "input_token_count": r.metrics.input_token_count if r.metrics else None,
                "output_token_count": r.metrics.output_token_count
                if r.metrics
                else None,
                "prefill_tps": r.metrics.prefill_tps if r.metrics else None,
                "decode_tps": r.metrics.decode_tps if r.metrics else None,
                "peak_java_memory_mb": r.metrics.peak_java_memory_mb
                if r.metrics
                else None,
                "peak_native_memory_mb": r.metrics.peak_native_memory_mb
                if r.metrics
                else None,
                "itl_p50_ms": r.metrics.itl_p50_ms if r.metrics else None,
                "itl_p95_ms": r.metrics.itl_p95_ms if r.metrics else None,
                "itl_p99_ms": r.metrics.itl_p99_ms if r.metrics else None,
                "timestamp": r.timestamp,
                "run_id": r.run_id,
            }
        )

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=llm_results.csv"},
    )


# ── Response Validation endpoints (Phase 4a) ─────────────────────────────────


@app.get("/api/validation/summary", response_model=ApiSuccess[ValidationSummary])
async def get_validation_summary(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
):
    data = await compute_validation_summary(
        _db(request),
        device=device,
        model=model,
        run_id=run_id,
    )
    return ApiSuccess(data=data)


@app.get(
    "/api/validation/by-category", response_model=ApiSuccess[List[CategoryValidation]]
)
async def get_validation_by_category(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
):
    data = await compute_validation_by_category(
        _db(request),
        device=device,
        model=model,
    )
    return ApiSuccess(data=data)


@app.get("/api/validation/by-model", response_model=ApiSuccess[List[ModelValidation]])
async def get_validation_by_model(
    request: Request,
    device: Optional[str] = Query(None),
):
    data = await compute_validation_by_model(_db(request), device=device)
    return ApiSuccess(data=data)


# ── Quantization Comparison endpoints (QUANT_COMPARISON_ARCHITECTURE §4) ──────


@app.get("/api/validation/quant-diff", response_model=ApiSuccess[List[QuantDiffItem]])
async def get_quant_diff(
    request: Request,
    device: Optional[str] = Query(None),
    base_model: Optional[str] = Query(None),
):
    data = await compute_quant_diff(
        _db(request), device=device, base_model=base_model,
    )
    return ApiSuccess(data=data)


@app.get("/api/quant/comparison", response_model=ApiSuccess[QuantComparisonResponse])
async def get_quant_comparison(
    request: Request,
    device: Optional[str] = Query(None),
    base_model: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
):
    data = await compute_quant_comparison(
        _db(request), device=device, base_model=base_model, run_id=run_id,
    )
    return ApiSuccess(data=data)


@app.get("/api/quant/similarity", response_model=ApiSuccess[QuantSimilarityResponse])
async def get_quant_similarity(
    request: Request,
    device: Optional[str] = Query(None),
    base_model: Optional[str] = Query(None),
):
    data = await compute_quant_similarity(
        _db(request), device=device, base_model=base_model,
    )
    return ApiSuccess(data=data)