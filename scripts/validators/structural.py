"""Structural evaluators for JSON, Python code, and markdown responses.

eval_json_structure:  JSON parse + optional expected key validation
eval_python_syntax:   ast.parse validity check
eval_markdown_table:  basic markdown table structure check
"""

import ast
import json
import re


def _extract_fenced_block(response: str, lang: str = "") -> str:
    """Extract content from markdown fenced code block, or return raw text."""
    pattern = rf'```(?:{lang})?\s*([\s\S]*?)```'
    match = re.search(pattern, response)
    return match.group(1).strip() if match else response.strip()


def eval_json_structure(response: str, ground_truth: str | None = None) -> tuple[str, str]:
    """Validate JSON structure in response.

    If ground_truth is provided as comma-separated key names (e.g. "name,age,city,hobbies"),
    also checks that parsed JSON object contains those keys.

    Returns:
        (status, detail) where status is 'pass' | 'fail'
    """
    text = _extract_fenced_block(response, "json")

    # Try to find JSON-like content if raw text isn't valid JSON
    if not text.startswith(("{", "[", '"')):
        # Look for first { or [ in the text
        for i, c in enumerate(text):
            if c in ("{", "["):
                text = text[i:]
                break

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return "fail", f"Invalid JSON: {e}"

    type_name = type(parsed).__name__

    # Key existence check when ground_truth specifies expected keys
    if ground_truth and isinstance(parsed, dict):
        expected_keys = [k.strip().lower() for k in ground_truth.split(",") if k.strip()]
        if expected_keys:
            actual_keys = {k.lower() for k in parsed.keys()}
            missing = [k for k in expected_keys if k not in actual_keys]
            if missing:
                return "fail", f"Valid JSON {type_name} but missing keys: {', '.join(missing)}"
            return "pass", f"Valid JSON {type_name} with all expected keys: {', '.join(expected_keys)}"

    # Array containment check when ground_truth specifies expected items
    if ground_truth and isinstance(parsed, list):
        expected_items = [k.strip().lower() for k in ground_truth.split(",") if k.strip()]
        if expected_items:
            actual_items = {str(item).lower() for item in parsed}
            missing = [item for item in expected_items if item not in actual_items]
            if missing:
                return "fail", f"Valid JSON {type_name} but missing items: {', '.join(missing)}"
            return "pass", f"Valid JSON {type_name} with all expected items"

    return "pass", f"Valid JSON: {type_name}"


def eval_python_syntax(response: str) -> tuple[str, str]:
    """Validate Python syntax using ast.parse.

    Returns:
        (status, detail) where status is 'pass' | 'fail'
    """
    text = _extract_fenced_block(response, "python")

    if not text:
        return "fail", "No Python code found in response"

    try:
        ast.parse(text)
        line_count = len(text.splitlines())
        return "pass", f"Valid Python syntax ({line_count} lines)"
    except SyntaxError as e:
        return "fail", f"Python syntax error: {e}"


def eval_markdown_table(response: str) -> tuple[str, str]:
    """Validate basic markdown table structure.

    Checks for at least a header row and a separator row (|---|).

    Returns:
        (status, detail) where status is 'pass' | 'fail'
    """
    lines = response.strip().splitlines()

    # Find lines that look like table rows (contain |)
    table_lines = [line.strip() for line in lines if "|" in line]
    if len(table_lines) < 2:
        return "fail", "No markdown table found (need at least header + separator)"

    # Check for separator row (contains ---)
    has_separator = any(
        re.match(r'^[\s|:-]+$', line) and "---" in line
        for line in table_lines
    )
    if not has_separator:
        return "fail", "Markdown table missing separator row (|---|)"

    return "pass", f"Valid markdown table ({len(table_lines)} rows including header/separator)"
