"""Deterministic evaluators for math and factoid/knowledge prompts.

eval_math:        exact numeric match with tolerance (±0.1%)
eval_containment: keyword containment with normalization + fallback to uncertain
"""

import math
import re


def eval_math(response: str, ground_truth: str) -> tuple[str, str]:
    """Evaluate math response against numeric ground truth.

    Strategy: extract all numbers from response, check from last to first
    (final answer is typically the last number in "237 + 485 = 722").

    Returns:
        (status, detail) where status is 'pass' | 'fail'
    """
    if not ground_truth:
        return "fail", "No ground_truth provided for deterministic eval"

    try:
        expected = float(ground_truth)
    except ValueError:
        return "fail", f"Invalid ground_truth: {ground_truth}"

    # Normalize response: lowercase + collapse whitespace
    norm_response = response.lower().strip()
    norm_response = re.sub(r'\s+', ' ', norm_response)

    # Extract all numeric values (including negative and decimal)
    numbers = re.findall(r'-?\d+\.?\d*', norm_response)
    if not numbers:
        return "fail", "No numeric value found in response"

    # Check from last to first — final answer is usually last
    for num_str in reversed(numbers):
        try:
            num = float(num_str)
        except ValueError:
            continue
        if math.isclose(num, expected, rel_tol=1e-3, abs_tol=1e-9):
            return "pass", f"Correct: {num_str} matches expected {ground_truth}"

    closest = min(numbers, key=lambda n: abs(float(n) - expected))
    return "fail", f"Incorrect: closest value {closest}, expected {ground_truth}"


def eval_containment(response: str, ground_truth: str) -> tuple[str, str]:
    """Evaluate by checking if ground_truth keyword(s) appear in response.

    Used for knowledge/factoid and reasoning categories.
    Normalization: lowercase, strip articles, remove punctuation.

    Returns:
        (status, detail) where status is 'pass' | 'uncertain'
        Note: never returns 'fail' — absence → uncertain (needs LLM judge in 4b)
    """
    if not ground_truth:
        return "uncertain", "No ground_truth provided — cannot evaluate"

    def normalize(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        # Strip common English articles — but only when surrounded by word boundaries
        # and followed by a space (to avoid stripping standalone "a" answers)
        text = re.sub(r'\b(the|an) ', ' ', text)
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    norm_truth = normalize(ground_truth)
    norm_response = normalize(response)

    if not norm_truth:
        return "uncertain", "Ground truth normalizes to empty"

    # Direct containment: ground_truth found in response
    if norm_truth in norm_response:
        return "pass", f"Ground truth '{ground_truth}' found in response"

    # Reverse containment: response is a subset of ground_truth (short answers)
    if norm_response and norm_response in norm_truth and len(norm_response) > 2:
        return "pass", f"Response is subset of ground truth"

    # Multi-keyword: if ground_truth contains comma-separated keywords, check each
    if "," in ground_truth:
        keywords = [normalize(k) for k in ground_truth.split(",") if k.strip()]
        matched = [k for k in keywords if k in norm_response]
        if len(matched) == len(keywords):
            return "pass", f"All keywords found: {', '.join(matched)}"
        if matched:
            return "pass", f"Partial keywords found: {', '.join(matched)} / {', '.join(keywords)}"

    return "uncertain", f"Ground truth '{ground_truth}' not found — needs LLM judge (Phase 4b)"
