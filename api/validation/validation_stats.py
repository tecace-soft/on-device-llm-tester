# ── Response Validation stats (Phase 4a) ────────────────────────────────────────
# APPEND this block to the end of api/stats.py
#
# Required imports (add to top of stats.py if not present):
#   from schemas import ValidationSummary, CategoryValidation, ModelValidation

async def compute_validation_summary(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    model: Optional[str] = None,
    run_id: Optional[str] = None,
) -> "ValidationSummary":
    """Compute validation status aggregation."""
    from schemas import ValidationSummary

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
) -> list["CategoryValidation"]:
    """Compute validation status per category."""
    from schemas import CategoryValidation

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
) -> list["ModelValidation"]:
    """Compute validation pass/fail/truncation rates per model."""
    from schemas import ModelValidation

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
        results.append(ModelValidation(
            model_name=row["model_name"],
            pass_rate=round((row["v_pass"] or 0) / evaluable, 4) if evaluable > 0 else 0.0,
            fail_rate=round((row["v_fail"] or 0) / evaluable, 4) if evaluable > 0 else 0.0,
            truncation_rate=round((row["truncated"] or 0) / total, 4) if total > 0 else 0.0,
            total=total,
        ))
    return results
