"""Sanity checks applied to every response regardless of eval_strategy.

Checks:
    - empty_response: response is blank after stripping
    - truncated: output_token_count >= 95% of max_tokens
    - gibberish: degenerate token repetition / broken encoding
"""

from collections import Counter
from typing import Optional


def check_empty(response: str) -> bool:
    """True if response is empty or whitespace-only."""
    return len(response.strip()) == 0


def check_truncated(output_token_count: Optional[int], max_tokens: int) -> bool:
    """True if output appears truncated (>= 95% of max_tokens).

    Args:
        output_token_count: actual output tokens from the result
        max_tokens: configured max_tokens from test_config.json model entry
    """
    if output_token_count is None or max_tokens <= 0:
        return False
    return output_token_count >= max_tokens * 0.95


def check_gibberish(response: str) -> bool:
    """Detect degenerate / gibberish output from SLM collapse.

    Three heuristics (any one triggers True):
    1. Word repetition: most frequent word > 50% of total words
    2. Low alphabet ratio: alphabetic chars < 20% of total length
    3. Consecutive identical chars: any char repeated 20+ times in a row
    """
    text = response.strip()
    if not text:
        return False  # empty handled separately

    # --- Heuristic 1: word-level repetition ---
    words = text.split()
    if len(words) >= 3:
        counts = Counter(words)
        most_common_count = counts.most_common(1)[0][1]
        if most_common_count / len(words) > 0.5:
            return True

    # --- Heuristic 2: low alphabet ratio ---
    # SLM degeneration sometimes produces streams of punctuation or control chars
    if len(text) >= 10:
        alnum_count = sum(1 for c in text if c.isalnum())
        if alnum_count / len(text) < 0.2:
            return True

    # --- Heuristic 3: consecutive identical characters ---
    # e.g. "aaaaaaaaaaaaaaaaaaaaaa" or "!!!!!!!!!!!!!!!!!!!!!!!!"
    if len(text) >= 20:
        streak = 1
        for i in range(1, len(text)):
            if text[i] == text[i - 1]:
                streak += 1
                if streak >= 20:
                    return True
            else:
                streak = 1

    return False


def run_sanity_checks(
    response: str,
    output_token_count: Optional[int],
    max_tokens: int,
) -> dict[str, bool]:
    """Run all sanity checks and return results dict.

    Returns:
        {"empty_response": bool, "truncated": bool, "gibberish": bool}
    """
    return {
        "empty_response": check_empty(response),
        "truncated": check_truncated(output_token_count, max_tokens),
        "gibberish": check_gibberish(response),
    }