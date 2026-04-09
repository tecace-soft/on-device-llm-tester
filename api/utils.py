"""
Quantization utility functions for model name parsing and comparison analysis.

Architecture: QUANT_COMPARISON_ARCHITECTURE.md §3, §6
Used by: api/stats.py (compute_quant_comparison), scripts/response_validator.py (compute_all_quant_diffs)
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.schemas import QuantBaseline, QuantComparisonItem

# GGUF quantization level pattern (llama.cpp standard)
# ref: https://github.com/ggerganov/llama.cpp/blob/master/examples/quantize/quantize.cpp
QUANT_PATTERN = re.compile(
    r'[-_]('
    r'Q[1-8]_[0-9A-Z_]+'       # Q2_K, Q3_K_M, Q4_K_S, Q5_K_M, Q6_K, Q8_0
    r'|IQ[1-4]_[A-Z0-9_]+'     # IQ1_S, IQ2_XXS, IQ3_M, IQ4_NL
    r'|F16|F32|BF16'            # full precision
    r')'
    r'(?:\.gguf)?$',
    re.IGNORECASE,
)

# MediaPipe quantization pattern (legacy .task models)
MEDIAPIPE_QUANT_PATTERN = re.compile(
    r'[-_](int[48]|fp16|fp32)'
    r'(?:\.task)?$',
    re.IGNORECASE,
)

# Precision ranking — higher = more precise, used for baseline selection
QUANT_RANK: dict[str, int] = {
    "F32": 100, "F16": 90, "BF16": 85,
    "Q8_0": 80,
    "Q6_K": 70,
    "Q5_K_M": 65, "Q5_K_S": 63,
    "Q4_K_M": 55, "Q4_K_S": 53, "Q4_0": 50,
    "Q3_K_L": 44, "Q3_K_M": 45, "Q3_K_S": 43,
    "Q2_K": 30,
    "IQ4_NL": 54, "IQ4_XS": 52,
    "IQ3_M": 42, "IQ3_XXS": 40,
    "IQ2_XXS": 25, "IQ2_XS": 26,
    "IQ1_S": 10,
    # MediaPipe — keys uppercased for case-insensitive lookup
    "INT8": 80, "INT4": 50, "FP16": 90, "FP32": 100,
}


def extract_base_and_quant(model_name: str) -> tuple[str, str]:
    """Split model name into (base_name, quant_level).

    Tries GGUF pattern first, then MediaPipe.
    Returns (model_name, "unknown") if no pattern matches.

    Examples:
        "gemma-4-E2B-it-Q3_K_M.gguf"  → ("gemma-4-E2B-it", "Q3_K_M")
        "gemma-4-E2B-it-Q8_0.gguf"    → ("gemma-4-E2B-it", "Q8_0")
        "gemma3-1b-it-int4.task"       → ("gemma3-1b-it", "int4")
        "some-unknown-model"           → ("some-unknown-model", "unknown")
    """
    m = QUANT_PATTERN.search(model_name)
    if m:
        return model_name[:m.start()], m.group(1)

    m = MEDIAPIPE_QUANT_PATTERN.search(model_name)
    if m:
        return model_name[:m.start()], m.group(1)

    return model_name, "unknown"


def select_baseline(quants: Sequence[QuantComparisonItem]) -> QuantComparisonItem:
    """Pick the highest-precision quantization as baseline for delta calculations.

    Uses QUANT_RANK lookup; unknown quant levels get rank 0.
    Depends on: QuantComparisonItem.quant_level
    """
    return max(quants, key=lambda q: QUANT_RANK.get(q.quant_level.upper(), 0))


def generate_insight(
    quants: Sequence[QuantComparisonItem],
    deltas: Sequence[QuantBaseline],
) -> str:
    """Produce a one-line trade-off insight from comparison data.

    Rules (Architecture §6.2):
      1. Recommend most efficient quant where pass_rate drop ≤ 5%
      2. If all quants drop > 5%, recommend keeping highest precision
      3. If any quant has < 10 results, flag insufficient data

    Used by: api/stats.py compute_quant_comparison()
    """
    # Data sufficiency check
    low_data = [q for q in quants if q.result_count < 10]
    if low_data:
        q = low_data[0]
        return (
            f"데이터 부족: 양자화당 10개 이상의 결과가 필요합니다 "
            f"(현재 {q.quant_level}: {q.result_count}개)"
        )

    baseline = select_baseline(quants)

    # Find best trade-off: pass_rate drop ≤ 5% AND (tps gain OR battery saving)
    best_candidate: QuantBaseline | None = None
    best_score: float = -1.0

    for delta in deltas:
        pr_change = delta.pass_rate_change_pct
        if pr_change is None:
            continue
        # Reject if quality drops more than 5%
        if pr_change < -5.0:
            continue

        score = 0.0
        if delta.tps_change_pct is not None and delta.tps_change_pct > 0:
            score += delta.tps_change_pct
        if delta.battery_change_pct is not None and delta.battery_change_pct < 0:
            score += abs(delta.battery_change_pct)

        if score > best_score:
            best_score = score
            best_candidate = delta

    if best_candidate is None:
        # All quants degrade quality > 5%
        worst = min(deltas, key=lambda d: d.pass_rate_change_pct or 0.0)
        return (
            f"{worst.baseline_quant} 유지 추천: 모든 저양자화에서 품질 5% 이상 하락 "
            f"(최대 {worst.pass_rate_change_pct:+.1f}%)"
        )

    # Find the quant_level for the best candidate — stored directly on QuantBaseline
    candidate_quant = best_candidate.quant_level
    parts = [f"{baseline.quant_level} 대비"]
    if best_candidate.pass_rate_change_pct is not None:
        parts.append(f"품질 {best_candidate.pass_rate_change_pct:+.1f}%")
    if best_candidate.tps_change_pct is not None:
        parts.append(f"속도 {best_candidate.tps_change_pct:+.1f}%")
    if best_candidate.battery_change_pct is not None:
        parts.append(f"배터리 {best_candidate.battery_change_pct:+.1f}%")

    return f"{candidate_quant} 추천: {', '.join(parts)} — 최적 trade-off"