"""
Tests for api/utils.py — quantization utility functions.

Architecture: QUANT_COMPARISON_ARCHITECTURE.md §3, §6
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure api/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from utils import (
    QUANT_PATTERN,
    MEDIAPIPE_QUANT_PATTERN,
    QUANT_RANK,
    extract_base_and_quant,
    select_baseline,
    generate_insight,
)


# ── extract_base_and_quant ────────────────────────────────────────────────────

class TestExtractBaseAndQuant:
    """GGUF, MediaPipe, and edge-case model name parsing."""

    @pytest.mark.parametrize("model_name, expected_base, expected_quant", [
        # Standard GGUF models
        ("gemma-4-E2B-it-Q3_K_M.gguf", "gemma-4-E2B-it", "Q3_K_M"),
        ("gemma-4-E2B-it-Q4_K_M.gguf", "gemma-4-E2B-it", "Q4_K_M"),
        ("gemma-4-E2B-it-Q8_0.gguf", "gemma-4-E2B-it", "Q8_0"),
        # GGUF without .gguf extension
        ("llama-3-8b-Q5_K_S", "llama-3-8b", "Q5_K_S"),
        ("phi-3-mini-Q6_K", "phi-3-mini", "Q6_K"),
        # Full precision
        ("model-F16.gguf", "model", "F16"),
        ("model-F32.gguf", "model", "F32"),
        ("model-BF16.gguf", "model", "BF16"),
        # IQ quantizations
        ("llama-IQ2_XXS.gguf", "llama", "IQ2_XXS"),
        ("model-IQ3_M.gguf", "model", "IQ3_M"),
        ("tiny-IQ4_NL.gguf", "tiny", "IQ4_NL"),
        # Underscore separator
        ("model_name_Q4_K_M.gguf", "model_name", "Q4_K_M"),
        # Q2 and Q1
        ("small-model-Q2_K.gguf", "small-model", "Q2_K"),
        ("nano-IQ1_S.gguf", "nano", "IQ1_S"),
    ])
    def test_gguf_patterns(self, model_name: str, expected_base: str, expected_quant: str):
        base, quant = extract_base_and_quant(model_name)
        assert base == expected_base
        assert quant == expected_quant

    @pytest.mark.parametrize("model_name, expected_base, expected_quant", [
        ("gemma3-1b-it-int4.task", "gemma3-1b-it", "int4"),
        ("gemma3-1b-it-int8.task", "gemma3-1b-it", "int8"),
        ("model-fp16.task", "model", "fp16"),
        ("model-fp32.task", "model", "fp32"),
        # Without .task extension
        ("gemma-int4", "gemma", "int4"),
    ])
    def test_mediapipe_patterns(self, model_name: str, expected_base: str, expected_quant: str):
        base, quant = extract_base_and_quant(model_name)
        assert base == expected_base
        assert quant == expected_quant

    @pytest.mark.parametrize("model_name", [
        "some-unknown-model",
        "plain-model-name",
        "no-quant-here.bin",
        "",
    ])
    def test_unknown_fallback(self, model_name: str):
        base, quant = extract_base_and_quant(model_name)
        assert base == model_name
        assert quant == "unknown"

    def test_case_insensitive(self):
        """Regex should match regardless of case."""
        base, quant = extract_base_and_quant("model-q4_k_m.gguf")
        assert base == "model"
        assert quant == "q4_k_m"

    def test_same_base_across_quants(self):
        """Different quants of same model should produce identical base names."""
        models = [
            "gemma-4-E2B-it-Q3_K_M.gguf",
            "gemma-4-E2B-it-Q4_K_M.gguf",
            "gemma-4-E2B-it-Q8_0.gguf",
        ]
        bases = {extract_base_and_quant(m)[0] for m in models}
        assert len(bases) == 1
        assert bases.pop() == "gemma-4-E2B-it"


# ── select_baseline ──────────────────────────────────────────────────────────

def _make_quant_item(quant_level: str, **kwargs) -> MagicMock:
    """Create a mock QuantComparisonItem with given quant_level."""
    item = MagicMock()
    item.quant_level = quant_level
    item.result_count = kwargs.get("result_count", 25)
    perf = MagicMock()
    perf.avg_decode_tps = kwargs.get("avg_decode_tps")
    perf.avg_latency_ms = kwargs.get("avg_latency_ms")
    item.performance = perf
    quality = MagicMock()
    quality.pass_rate = kwargs.get("pass_rate", 0.8)
    item.quality = quality
    return item


class TestSelectBaseline:

    def test_picks_highest_precision(self):
        quants = [
            _make_quant_item("Q3_K_M"),
            _make_quant_item("Q4_K_M"),
            _make_quant_item("Q8_0"),
        ]
        baseline = select_baseline(quants)
        assert baseline.quant_level == "Q8_0"

    def test_f16_over_q8(self):
        quants = [
            _make_quant_item("Q8_0"),
            _make_quant_item("F16"),
        ]
        baseline = select_baseline(quants)
        assert baseline.quant_level == "F16"

    def test_mediapipe_fp32_highest(self):
        quants = [
            _make_quant_item("int4"),
            _make_quant_item("int8"),
            _make_quant_item("fp32"),
        ]
        baseline = select_baseline(quants)
        assert baseline.quant_level == "fp32"

    def test_unknown_quant_gets_rank_zero(self):
        quants = [
            _make_quant_item("WEIRD_QUANT"),
            _make_quant_item("Q3_K_M"),
        ]
        baseline = select_baseline(quants)
        assert baseline.quant_level == "Q3_K_M"


# ── generate_insight ─────────────────────────────────────────────────────────

def _make_delta(
    baseline_quant: str = "Q8_0",
    quant_level: str = "Q3_K_M",
    tps_pct: float | None = None,
    latency_pct: float | None = None,
    pass_rate_pct: float | None = None,
    battery_pct: float | None = None,
) -> MagicMock:
    d = MagicMock()
    d.baseline_quant = baseline_quant
    d.quant_level = quant_level
    d.tps_change_pct = tps_pct
    d.latency_change_pct = latency_pct
    d.pass_rate_change_pct = pass_rate_pct
    d.battery_change_pct = battery_pct
    return d


class TestGenerateInsight:

    def test_low_data_warning(self):
        quants = [
            _make_quant_item("Q8_0", result_count=25),
            _make_quant_item("Q3_K_M", result_count=5),
        ]
        deltas = [_make_delta(pass_rate_pct=-3.0)]
        insight = generate_insight(quants, deltas)
        assert "데이터 부족" in insight
        assert "Q3_K_M" in insight

    def test_all_degraded(self):
        """When all quants drop > 5% quality, recommend keeping baseline."""
        quants = [
            _make_quant_item("Q8_0", result_count=25, avg_decode_tps=10.0),
            _make_quant_item("Q3_K_M", result_count=25, avg_decode_tps=15.0),
        ]
        deltas = [_make_delta(pass_rate_pct=-16.7, tps_pct=50.0)]
        insight = generate_insight(quants, deltas)
        assert "유지 추천" in insight

    def test_good_tradeoff_recommended(self):
        """When a quant has ≤5% quality drop with perf gains, recommend it."""
        quants = [
            _make_quant_item("Q8_0", result_count=25, avg_decode_tps=10.0),
            _make_quant_item("Q4_K_M", result_count=25, avg_decode_tps=13.0),
        ]
        # Q4_K_M: -3% quality, +30% speed, -25% battery
        deltas = [_make_delta(
            quant_level="Q4_K_M",
            pass_rate_pct=-3.0,
            tps_pct=30.0,
            battery_pct=-25.0,
        )]
        insight = generate_insight(quants, deltas)
        assert "추천" in insight
        assert "trade-off" in insight


# ── QUANT_RANK completeness ──────────────────────────────────────────────────

class TestQuantRank:

    def test_f32_is_highest(self):
        assert QUANT_RANK["F32"] == 100

    def test_iq1_s_is_lowest_standard(self):
        assert QUANT_RANK["IQ1_S"] == 10

    def test_mediapipe_int8_equals_q8(self):
        """int8 and Q8_0 should have same precision rank."""
        assert QUANT_RANK["INT8"] == QUANT_RANK["Q8_0"]