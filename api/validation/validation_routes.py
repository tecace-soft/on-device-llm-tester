# ── Response Validation endpoints (Phase 4a) ────────────────────────────────────
# APPEND this block to api/main.py
#
# Required additions to imports at top of main.py:
#   from schemas import ValidationSummary, CategoryValidation, ModelValidation, QuantDiffItem
#   from stats import compute_validation_summary, compute_validation_by_category, compute_validation_by_model
#
# Also add ?validation_status filter to existing GET /api/results endpoint's load_all call.


@app.get("/api/validation/summary", response_model=ApiSuccess[ValidationSummary])
async def get_validation_summary(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
):
    data = await compute_validation_summary(
        _db(request), device=device, model=model, run_id=run_id,
    )
    return ApiSuccess(data=data)


@app.get("/api/validation/by-category", response_model=ApiSuccess[List[CategoryValidation]])
async def get_validation_by_category(
    request: Request,
    device: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
):
    data = await compute_validation_by_category(
        _db(request), device=device, model=model,
    )
    return ApiSuccess(data=data)


@app.get("/api/validation/by-model", response_model=ApiSuccess[List[ModelValidation]])
async def get_validation_by_model(
    request: Request,
    device: Optional[str] = Query(None),
):
    data = await compute_validation_by_model(_db(request), device=device)
    return ApiSuccess(data=data)
