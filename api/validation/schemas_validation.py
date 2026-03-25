# ── Response Validation shapes (Phase 4a) ───────────────────────────────────────
# APPEND this block to the end of api/schemas.py

class ValidationSummary(BaseModel):
    total: int
    pass_count: int
    fail_count: int
    warn_count: int
    uncertain_count: int
    skip_count: int
    pass_rate: float                    # pass / (total - skip)


class CategoryValidation(BaseModel):
    category: str
    pass_count: int
    fail_count: int
    warn_count: int
    uncertain_count: int
    total: int


class ModelValidation(BaseModel):
    model_name: str
    pass_rate: float
    fail_rate: float
    truncation_rate: float
    total: int


class QuantDiffItem(BaseModel):
    prompt_id: str
    prompt_text: str
    model_a: str
    model_b: str
    match_ratio: float
    a_length: int
    b_length: int
