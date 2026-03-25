"""Unit tests for scripts/validators/ modules.

Run: python -m pytest tests/test_validators.py -v
  or: python tests/test_validators.py  (standalone)
"""

import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from validators.sanity import check_empty, check_truncated, check_gibberish, run_sanity_checks
from validators.deterministic import eval_math, eval_containment
from validators.structural import eval_json_structure, eval_python_syntax, eval_markdown_table


# ═══════════════════════════════════════════════════════════════════════════════
# sanity.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckEmpty:
    def test_empty_string(self):
        assert check_empty("") is True

    def test_whitespace_only(self):
        assert check_empty("   \n\t  ") is True

    def test_non_empty(self):
        assert check_empty("Hello") is False

    def test_single_char(self):
        assert check_empty("a") is False


class TestCheckTruncated:
    def test_truncated_at_limit(self):
        assert check_truncated(1024, 1024) is True

    def test_truncated_at_95_percent(self):
        assert check_truncated(973, 1024) is True  # 973 >= 972.8

    def test_not_truncated(self):
        assert check_truncated(500, 1024) is False

    def test_none_token_count(self):
        assert check_truncated(None, 1024) is False

    def test_zero_max_tokens(self):
        assert check_truncated(100, 0) is False


class TestCheckGibberish:
    def test_normal_text(self):
        assert check_gibberish("The capital of France is Paris.") is False

    def test_repeated_word(self):
        assert check_gibberish("the the the the the the the the the the") is True

    def test_short_text(self):
        assert check_gibberish("OK") is False

    def test_empty(self):
        assert check_gibberish("") is False

    def test_low_alnum_ratio(self):
        # 20+ chars of non-alphanumeric
        assert check_gibberish("!@#$%^&*()!@#$%^&*()!@#$%^&*()") is True

    def test_numeric_response_not_gibberish(self):
        # Math response with numbers should NOT be flagged
        assert check_gibberish("237 + 485 = 722") is False

    def test_consecutive_chars(self):
        assert check_gibberish("a" * 25) is True

    def test_mixed_normal(self):
        assert check_gibberish("Hello world! This is a normal response with some numbers 123.") is False

    def test_broken_utf8_like(self):
        # Simulating broken encoding output
        assert check_gibberish("ÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿÿ") is True


class TestRunSanityChecks:
    def test_all_clear(self):
        result = run_sanity_checks("Normal response", 100, 1024)
        assert result == {"empty_response": False, "truncated": False, "gibberish": False}

    def test_empty_and_truncated(self):
        result = run_sanity_checks("", 1024, 1024)
        assert result["empty_response"] is True
        assert result["truncated"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# deterministic.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvalMath:
    def test_exact_match(self):
        status, _ = eval_math("722", "722")
        assert status == "pass"

    def test_match_in_sentence(self):
        status, _ = eval_math("The answer is 722.", "722")
        assert status == "pass"

    def test_match_with_calculation(self):
        status, _ = eval_math("237 + 485 = 722", "722")
        assert status == "pass"

    def test_wrong_answer(self):
        status, detail = eval_math("The answer is 723.", "722")
        assert status == "fail"
        assert "723" in detail

    def test_no_numbers(self):
        status, _ = eval_math("I don't know", "722")
        assert status == "fail"

    def test_negative_number(self):
        status, _ = eval_math("The result is -0.79", "-0.79")
        assert status == "pass"

    def test_tolerance(self):
        # 722.001 should match 722 within 0.1% tolerance
        status, _ = eval_math("722.001", "722")
        assert status == "pass"

    def test_decimal_answer(self):
        status, _ = eval_math("The speed is 80 km/h", "80")
        assert status == "pass"

    def test_no_ground_truth(self):
        status, _ = eval_math("42", "")
        assert status == "fail"

    def test_invalid_ground_truth(self):
        status, _ = eval_math("42", "not_a_number")
        assert status == "fail"

    def test_float_subtraction(self):
        # 9.11 - 9.9 = -0.79
        status, _ = eval_math("9.11 - 9.9 = -0.79", "-0.79")
        assert status == "pass"


class TestEvalContainment:
    def test_exact_keyword(self):
        status, _ = eval_containment("The capital of France is Paris.", "Paris")
        assert status == "pass"

    def test_case_insensitive(self):
        status, _ = eval_containment("The answer is paris.", "Paris")
        assert status == "pass"

    def test_with_articles(self):
        status, _ = eval_containment("The answer is the Paris.", "Paris")
        assert status == "pass"

    def test_not_found(self):
        status, _ = eval_containment("The capital of France is Lyon.", "Paris")
        assert status == "uncertain"

    def test_short_answer_match(self):
        # Single-letter answer "A" should match ground_truth "A" via containment
        status, _ = eval_containment("The tallest is A.", "A")
        assert status == "pass"

    def test_short_answer_reverse_subset(self):
        # Response "Paris" is subset of "Paris, France"
        status, _ = eval_containment("Paris", "Paris, France")
        assert status == "pass"

    def test_no_ground_truth(self):
        status, _ = eval_containment("Some response", "")
        assert status == "uncertain"

    def test_h2o_formula(self):
        status, _ = eval_containment("The chemical formula for water is H2O.", "H2O")
        assert status == "pass"

    def test_multi_keyword(self):
        # comma-separated keywords all present
        status, _ = eval_containment(
            "Paris is the capital city of France, located in Europe.",
            "Paris,France"
        )
        assert status == "pass"

    def test_multi_keyword_partial(self):
        status, _ = eval_containment(
            "Paris is a beautiful city.",
            "Paris,France"
        )
        assert status == "pass"  # partial match still passes

    def test_no_answer(self):
        status, _ = eval_containment(
            "No, we cannot definitively say that.",
            "No"
        )
        assert status == "pass"


# ═══════════════════════════════════════════════════════════════════════════════
# structural.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvalJsonStructure:
    def test_valid_array(self):
        status, _ = eval_json_structure('["apple", "banana", "grape", "mango"]')
        assert status == "pass"

    def test_valid_object(self):
        status, _ = eval_json_structure('{"name": "Alice", "age": 30}')
        assert status == "pass"

    def test_fenced_json(self):
        response = '```json\n{"key": "value"}\n```'
        status, _ = eval_json_structure(response)
        assert status == "pass"

    def test_invalid_json(self):
        status, _ = eval_json_structure("this is not json")
        assert status == "fail"

    def test_expected_keys_present(self):
        response = '{"name": "Alice", "age": 30, "city": "NYC", "hobbies": ["coding"]}'
        status, detail = eval_json_structure(response, "name,age,city,hobbies")
        assert status == "pass"
        assert "all expected keys" in detail

    def test_expected_keys_missing(self):
        response = '{"name": "Alice", "age": 30}'
        status, detail = eval_json_structure(response, "name,age,city,hobbies")
        assert status == "fail"
        assert "missing keys" in detail

    def test_expected_items_in_array(self):
        response = '["apple", "banana", "grape", "mango"]'
        status, _ = eval_json_structure(response, "apple,banana,grape,mango")
        assert status == "pass"

    def test_expected_items_missing(self):
        response = '["apple", "banana"]'
        status, detail = eval_json_structure(response, "apple,banana,grape,mango")
        assert status == "fail"
        assert "missing items" in detail

    def test_json_embedded_in_text(self):
        response = 'Here is the result: {"name": "Bob", "age": 25}'
        status, _ = eval_json_structure(response)
        assert status == "pass"


class TestEvalPythonSyntax:
    def test_valid_function(self):
        code = '''```python
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
```'''
        status, detail = eval_python_syntax(code)
        assert status == "pass"
        assert "lines" in detail

    def test_valid_class(self):
        code = '''```python
class Stack:
    def __init__(self):
        self.items = []
    def push(self, item):
        self.items.append(item)
```'''
        status, _ = eval_python_syntax(code)
        assert status == "pass"

    def test_invalid_syntax(self):
        code = "def foo(\n    return 42"
        status, detail = eval_python_syntax(code)
        assert status == "fail"
        assert "syntax error" in detail.lower()

    def test_empty_code(self):
        status, _ = eval_python_syntax("")
        assert status == "fail"

    def test_raw_code_no_fence(self):
        code = "def add(a, b):\n    return a + b"
        status, _ = eval_python_syntax(code)
        assert status == "pass"


class TestEvalMarkdownTable:
    def test_valid_table(self):
        table = """| Language | Typing | Speed |
|----------|--------|-------|
| Python   | Dynamic| Slow  |
| Rust     | Static | Fast  |"""
        status, _ = eval_markdown_table(table)
        assert status == "pass"

    def test_no_table(self):
        status, _ = eval_markdown_table("This is just text without any table.")
        assert status == "fail"

    def test_missing_separator(self):
        text = "| A | B |\n| C | D |"
        status, _ = eval_markdown_table(text)
        assert status == "fail"


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ═══════════════════════════════════════════════════════════════════════════════

def _run_standalone():
    """Run all tests without pytest."""
    import traceback

    test_classes = [
        TestCheckEmpty, TestCheckTruncated, TestCheckGibberish, TestRunSanityChecks,
        TestEvalMath, TestEvalContainment,
        TestEvalJsonStructure, TestEvalPythonSyntax, TestEvalMarkdownTable,
    ]

    total = passed = failed = 0
    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in methods:
            total += 1
            try:
                getattr(instance, method_name)()
                passed += 1
                print(f"  ✓ {cls.__name__}.{method_name}")
            except Exception:
                failed += 1
                print(f"  ✗ {cls.__name__}.{method_name}")
                traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    _run_standalone()