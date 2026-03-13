from __future__ import annotations

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

from loader import list_categories, list_devices, list_models, load_all
from schemas import ApiError, ApiSuccess, CompareResult, PaginationMeta, ResultItem, SummaryStats
from stats import compute_by_category, compute_by_model, compute_compare, compute_summary

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY")  # optional — skip auth if not set
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
RESULTS_DIR = os.getenv("RESULTS_DIR", "./results")

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="On-Device LLM Tester API",
    description="Benchmark results API for on-device LLM inference",
    version="1.0.0",
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


# ── Common filter params ───────────────────────────────────────────────────────
def _load(
    device: Optional[str],
    model: Optional[str],
    category: Optional[str],
    backend: Optional[str],
    status: Optional[str],
) -> List[ResultItem]:
    return load_all(
        results_dir=RESULTS_DIR,
        device=device,
        model=model,
        category=category,
        backend=backend,
        status=status if status != "all" else None,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/results", response_model=ApiSuccess[List[ResultItem]])
async def get_results(
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="success | error | all"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = _load(device, model, category, backend, status)
    total = len(rows)
    page = rows[offset: offset + limit]
    return ApiSuccess(
        data=page,
        meta=PaginationMeta(total=total, limit=limit, offset=offset, has_more=offset + limit < total),
    )


@app.get("/api/results/summary", response_model=ApiSuccess[SummaryStats])
async def get_summary(
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    rows = _load(device, model, category, backend, status)
    return ApiSuccess(data=compute_summary(rows))


@app.get("/api/results/by-model", response_model=ApiSuccess[list])
async def get_by_model(
    device: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    rows = _load(device, None, category, backend, None)
    return ApiSuccess(data=compute_by_model(rows))


@app.get("/api/results/by-category", response_model=ApiSuccess[list])
async def get_by_category(
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    rows = _load(device, model, None, backend, None)
    return ApiSuccess(data=compute_by_category(rows))


@app.get("/api/results/compare", response_model=ApiSuccess[List[CompareResult]])
async def get_compare(
    models: str = Query(..., description="Comma-separated model names, e.g. gemma3,qwen2.5"),
    device: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
):
    model_names = [m.strip() for m in models.split(",") if m.strip()]
    if len(model_names) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 model names")

    rows = _load(device, None, None, backend, None)
    # filter to requested models only
    rows = [r for r in rows if r.model_name in model_names]
    return ApiSuccess(data=compute_compare(rows, model_names))


@app.get("/api/models", response_model=ApiSuccess[List[str]])
async def get_models(device: Optional[str] = Query(None)):
    return ApiSuccess(data=list_models(RESULTS_DIR, device))


@app.get("/api/devices", response_model=ApiSuccess[List[str]])
async def get_devices():
    return ApiSuccess(data=list_devices(RESULTS_DIR))


@app.get("/api/categories", response_model=ApiSuccess[List[str]])
async def get_categories():
    return ApiSuccess(data=list_categories(RESULTS_DIR))


@app.get("/api/export/csv")
async def export_csv(
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    rows = _load(device, model, category, backend, status)
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
        m = r.metrics or {}
        row = {
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
        }
        writer.writerow(row)

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