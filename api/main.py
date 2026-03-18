import csv
import io
import logging
import os
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

import aiosqlite
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from db import lifespan
from loader import list_categories, list_devices, list_models, load_all
from schemas import ApiError, ApiSuccess, CategorySummary, CompareResult, ModelSummary, PaginationMeta, ResultItem, SummaryStats
from stats import compute_by_category, compute_by_model, compute_compare, compute_summary

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
    version="1.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth middleware (optional) ─────────────────────────────────────────────────
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/api"):
        if request.headers.get("X-API-Key") != API_KEY:
            return JSONResponse(
                status_code=401,
                content=ApiError(error="Invalid API key").model_dump(),
            )
    return await call_next(request)


# ── Global exception handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ApiError(error="Internal error", detail=str(exc)).model_dump(),
    )


# ── DB dependency ──────────────────────────────────────────────────────────────
def _db(request: Request) -> aiosqlite.Connection:
    return request.app.state.db


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/results", response_model=ApiSuccess[List[ResultItem]])
async def get_results(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="success | error | all"),
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
        limit=limit,
        offset=offset,
    )
    return ApiSuccess(
        data=rows,
        meta=PaginationMeta(total=total, limit=limit, offset=offset, has_more=offset + limit < total),
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
    data = await compute_by_model(_db(request), device=device, category=category, backend=backend)
    return ApiSuccess(data=data)


@app.get("/api/results/by-category", response_model=ApiSuccess[List[CategorySummary]])
async def get_by_category(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    data = await compute_by_category(_db(request), device=device, model=model, backend=backend)
    return ApiSuccess(data=data)


@app.get("/api/results/compare", response_model=ApiSuccess[List[CompareResult]])
async def get_compare(
    request: Request,
    models: str = Query(..., description="Comma-separated model names, e.g. gemma3,qwen2.5"),
    device: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    model_names = [m.strip() for m in models.split(",") if m.strip()]
    if len(model_names) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 model names")
    data = await compute_compare(_db(request), model_names=model_names, device=device, backend=backend)
    return ApiSuccess(data=data)


@app.get("/api/models", response_model=ApiSuccess[List[str]])
async def get_models(request: Request, device: Optional[str] = Query(None)):
    return ApiSuccess(data=await list_models(_db(request), device=device))


@app.get("/api/devices", response_model=ApiSuccess[List[str]])
async def get_devices(request: Request):
    return ApiSuccess(data=await list_devices(_db(request)))


@app.get("/api/categories", response_model=ApiSuccess[List[str]])
async def get_categories(request: Request):
    return ApiSuccess(data=await list_categories(_db(request)))


@app.get("/api/export/csv")
async def export_csv(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    rows, total = await load_all(
        _db(request),
        device=device,
        model=model,
        category=category,
        backend=backend,
        status=status if status != "all" else None,
        limit=10_000,
        offset=0,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data matching filters")

    fieldnames = [
        "status", "prompt_id", "prompt_category", "prompt_lang",
        "model_name", "backend",
        "device_manufacturer", "device_model", "device_soc", "android_version",
        "prompt", "response",
        "latency_ms", "init_time_ms",
        "ttft_ms", "prefill_time_ms", "decode_time_ms",
        "input_token_count", "output_token_count",
        "prefill_tps", "decode_tps",
        "peak_java_memory_mb", "peak_native_memory_mb",
        "itl_p50_ms", "itl_p95_ms", "itl_p99_ms",
        "timestamp",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "status": r.status,
            "prompt_id": r.prompt_id,
            "prompt_category": r.prompt_category,
            "prompt_lang": r.prompt_lang,
            "model_name": r.model_name,
            "backend": r.backend,
            "device_manufacturer": r.device.manufacturer,
            "device_model": r.device.model,
            "device_soc": r.device.soc,
            "android_version": r.device.android_version,
            "prompt": r.prompt,
            "response": r.response,
            "latency_ms": r.latency_ms,
            "init_time_ms": r.init_time_ms,
            "ttft_ms": r.metrics.ttft_ms if r.metrics else "",
            "prefill_time_ms": r.metrics.prefill_time_ms if r.metrics else "",
            "decode_time_ms": r.metrics.decode_time_ms if r.metrics else "",
            "input_token_count": r.metrics.input_token_count if r.metrics else "",
            "output_token_count": r.metrics.output_token_count if r.metrics else "",
            "prefill_tps": r.metrics.prefill_tps if r.metrics else "",
            "decode_tps": r.metrics.decode_tps if r.metrics else "",
            "peak_java_memory_mb": r.metrics.peak_java_memory_mb if r.metrics else "",
            "peak_native_memory_mb": r.metrics.peak_native_memory_mb if r.metrics else "",
            "itl_p50_ms": r.metrics.itl_p50_ms if r.metrics else "",
            "itl_p95_ms": r.metrics.itl_p95_ms if r.metrics else "",
            "itl_p99_ms": r.metrics.itl_p99_ms if r.metrics else "",
            "timestamp": r.timestamp,
        })

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results_export.csv"},
    )


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)