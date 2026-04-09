"""
response_validator.py — Response Validation Pipeline (Phase 4a)

Reads results from DB, runs sanity checks + deterministic evals,
writes validation_status and validation_detail back to results table.

Usage:
    # Validate all unvalidated results
    python scripts/response_validator.py

    # Validate specific CI run
    python scripts/response_validator.py --run-id 12345678

    # Dry run (no DB writes)
    python scripts/response_validator.py --dry-run

    # Force re-validate all (overwrite existing)
    python scripts/response_validator.py --force

    # Quantization diff report
    python scripts/response_validator.py --quant-diff

    # Summary only (CI output)
    python scripts/response_validator.py --summary-only
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

# ── Path setup ────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

from validators.sanity import run_sanity_checks, check_gibberish
from validators.deterministic import eval_math, eval_containment
from validators.structural import eval_json_structure, eval_python_syntax, eval_markdown_table
from utils import extract_base_and_quant

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH     = Path(os.getenv("DB_PATH",     str(_PROJECT_ROOT / "api" / "data" / "llm_tester.db")))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", str(_PROJECT_ROOT / "test_config.json")))


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    result_id: int
    status: str                    # pass | fail | warn | uncertain | skip
    detail: dict = field(default_factory=dict)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        logger.error("Database not found: %s", DB_PATH)
        sys.exit(1)
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def fetch_pending(con: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    """Fetch results that need validation."""
    query = """
        SELECT r.id, r.response, r.status, r.output_token_count,
               p.prompt_text, p.prompt_id AS prompt_code, p.category,
               p.ground_truth, p.eval_strategy,
               m.model_name
        FROM results r
        JOIN prompts p ON r.prompt_id = p.id
        JOIN models  m ON r.model_id  = m.id
    """
    conditions = []
    params: list = []

    if not args.force:
        conditions.append("r.validation_status IS NULL")

    if args.run_id:
        conditions.append("r.run_id = (SELECT id FROM runs WHERE run_id = ?)")
        params.append(args.run_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY r.id"

    return con.execute(query, params).fetchall()


def update_validation(con: sqlite3.Connection, results: list[ValidationResult]) -> None:
    """Batch update validation_status and validation_detail in results table."""
    if not results:
        return
    try:
        con.executemany(
            "UPDATE results SET validation_status = ?, validation_detail = ? WHERE id = ?",
            [(r.status, json.dumps(r.detail, ensure_ascii=False), r.result_id) for r in results],
        )
        con.commit()
        logger.info("Updated %d results in DB", len(results))
    except Exception as e:
        con.rollback()
        logger.error("DB update failed, rolled back: %s", e)
        raise


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load test_config.json for max_tokens lookup.

    Returns dict with 'max_tokens' (default per model) and 'prompts' map.
    """
    if not config_path.exists():
        logger.warning("Config not found: %s — using defaults", config_path)
        return {"max_tokens": 1024}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Config parse failed: %s — using defaults", e)
        return {"max_tokens": 1024}

    # Extract max_tokens from first model (all models in current config share same value)
    models = raw.get("models", [])
    max_tokens = models[0].get("max_tokens", 1024) if models else 1024

    return {"max_tokens": max_tokens}


# ── Core validation logic ─────────────────────────────────────────────────────

def determine_status(checks: dict, eval_result: Optional[dict]) -> str:
    """Combine sanity checks + eval result into final validation_status."""
    # eval fail → fail
    if eval_result and eval_result["result"] == "fail":
        return "fail"
    # eval uncertain → uncertain
    if eval_result and eval_result["result"] == "uncertain":
        return "uncertain"
    # sanity warnings → warn
    if checks.get("truncated") or checks.get("gibberish"):
        return "warn"
    # eval pass → pass
    if eval_result and eval_result["result"] == "pass":
        return "pass"
    # no eval (none strategy) + sanity clear → pass
    return "pass"


def validate_row(row: sqlite3.Row, config: dict) -> ValidationResult:
    """Run full validation pipeline on a single result row."""
    result_id = row["id"]

    # error status → skip immediately
    if row["status"] == "error":
        return ValidationResult(result_id, "skip", {
            "checks": {},
            "eval": None,
            "quant_diff": None,
        })

    response = row["response"] or ""
    eval_strategy = row["eval_strategy"] or "none"
    ground_truth = row["ground_truth"]
    category = row["category"] or ""
    max_tokens = config.get("max_tokens", 1024)

    # Sanity checks
    checks = run_sanity_checks(response, row["output_token_count"], max_tokens)

    # Empty response → fail immediately
    if checks["empty_response"]:
        return ValidationResult(result_id, "fail", {
            "checks": checks,
            "eval": None,
            "quant_diff": None,
        })

    # Deterministic eval based on strategy
    eval_result = None

    if eval_strategy == "deterministic":
        if not ground_truth:
            eval_result = {"strategy": "deterministic", "result": "fail",
                           "detail": "No ground_truth for deterministic eval"}
        else:
            status, detail = eval_math(response, ground_truth)
            eval_result = {"strategy": "deterministic", "result": status, "detail": detail}

    elif eval_strategy == "deterministic_with_fallback":
        if not ground_truth:
            eval_result = {"strategy": "deterministic_with_fallback", "result": "uncertain",
                           "detail": "No ground_truth provided"}
        else:
            status, detail = eval_containment(response, ground_truth)
            eval_result = {"strategy": "deterministic_with_fallback", "result": status, "detail": detail}

    elif eval_strategy == "structural":
        if category == "code":
            status, detail = eval_python_syntax(response)
        elif category == "structured_output" and ground_truth:
            # Check if ground_truth looks like expected keys (no JSON brackets)
            if not ground_truth.strip().startswith(("{", "[", '"')):
                status, detail = eval_json_structure(response, ground_truth)
            else:
                status, detail = eval_json_structure(response)
        elif category == "structured_output":
            # Try JSON first, fall back to markdown table
            status, detail = eval_json_structure(response)
            if status == "fail" and "|" in response:
                status, detail = eval_markdown_table(response)
        else:
            status, detail = eval_json_structure(response)
        eval_result = {"strategy": "structural", "result": status, "detail": detail}

    elif eval_strategy == "none":
        # No deterministic eval — sanity checks only
        eval_result = None

    else:
        logger.warning("Unknown eval_strategy '%s' for result %d — treating as 'none'",
                        eval_strategy, result_id)
        eval_result = None

    final_status = determine_status(checks, eval_result)

    return ValidationResult(result_id, final_status, {
        "checks": checks,
        "eval": eval_result,
        "quant_diff": None,
    })


# ── Quantization diff ─────────────────────────────────────────────────────────

def compute_all_quant_diffs(con: sqlite3.Connection) -> list[dict]:
    """Compare responses across different quantizations for same prompt + model base.

    Groups by (prompt_id, base_model) using extract_base_and_quant(),
    then computes SequenceMatcher ratio between response pairs.

    Architecture: QUANT_COMPARISON_ARCHITECTURE.md §3.4
    Depends on: api/utils.py extract_base_and_quant()
    """
    rows = con.execute("""
        SELECT p.prompt_id, p.prompt_text, m.model_name,
               r.response, r.status
        FROM results r
        JOIN prompts p ON r.prompt_id = p.id
        JOIN models  m ON r.model_id  = m.id
        WHERE r.status = 'success' AND r.response != ''
        ORDER BY p.prompt_id, m.model_name
    """).fetchall()

    # Group by (prompt_id, base_model) — only compare same-base quants
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        base, quant = extract_base_and_quant(row["model_name"])
        if quant == "unknown":
            continue
        key = (row["prompt_id"], base)
        if key not in groups:
            groups[key] = []
        groups[key].append({
            "model_name": row["model_name"],
            "response": row["response"],
            "prompt_text": row["prompt_text"],
        })

    diffs = []
    for (pid, _base), entries in groups.items():
        if len(entries) < 2:
            continue
        # Compare all pairs
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a = entries[i]
                b = entries[j]
                # Normalize before comparison
                a_norm = re.sub(r'\s+', ' ', a["response"].lower().strip())
                b_norm = re.sub(r'\s+', ' ', b["response"].lower().strip())
                ratio = SequenceMatcher(None, a_norm.split(), b_norm.split()).ratio()
                diffs.append({
                    "prompt_id": pid,
                    "prompt_text": a["prompt_text"][:80],
                    "model_a": a["model_name"],
                    "model_b": b["model_name"],
                    "match_ratio": round(ratio, 3),
                    "a_length": len(a["response"]),
                    "b_length": len(b["response"]),
                })

    return diffs


def print_quant_report(diffs: list[dict]) -> None:
    """Print quantization diff report to stdout."""
    if not diffs:
        print("\nNo quantization diffs found (need 2+ models with same prompts)")
        return

    print(f"\n{'='*80}")
    print("Quantization Diff Report")
    print(f"{'='*80}")
    print(f"{'Prompt':<30} {'Model A':<20} {'Model B':<20} {'Match':>6}")
    print(f"{'-'*30} {'-'*20} {'-'*20} {'-'*6}")
    for d in diffs:
        prompt = d["prompt_text"][:28]
        print(f"{prompt:<30} {d['model_a']:<20} {d['model_b']:<20} {d['match_ratio']:>5.1%}")
    print()


# ── Summary ───────────────────────────────────────────────────────────────────

def print_validation_summary(results: list[ValidationResult]) -> None:
    """Print validation results summary."""
    if not results:
        print("\nNo results to validate (all already validated or no data)")
        return

    counts = {"pass": 0, "fail": 0, "warn": 0, "uncertain": 0, "skip": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    total = len(results)
    evaluable = total - counts["skip"]
    pass_rate = counts["pass"] / evaluable if evaluable > 0 else 0.0

    print(f"\n{'='*60}")
    print("Response Validation Summary")
    print(f"{'='*60}")
    print(f"  Total validated : {total}")
    print(f"  Pass            : {counts['pass']}")
    print(f"  Fail            : {counts['fail']}")
    print(f"  Warn            : {counts['warn']}")
    print(f"  Uncertain       : {counts['uncertain']}")
    print(f"  Skip            : {counts['skip']}")
    print(f"  Pass Rate       : {pass_rate:.1%} (excluding skips)")
    print(f"{'='*60}")

    # Show fail details
    fails = [r for r in results if r.status == "fail"]
    if fails:
        print(f"\nFailed validations ({len(fails)}):")
        for r in fails:
            eval_info = r.detail.get("eval", {})
            detail = eval_info.get("detail", "empty response") if eval_info else "empty response"
            print(f"  result_id={r.result_id}: {detail}")


def print_summary_only(con: sqlite3.Connection) -> None:
    """Print existing validation stats from DB (for --summary-only)."""
    row = con.execute("""
        SELECT
            COUNT(validation_status)                                        AS validated,
            SUM(CASE WHEN validation_status='pass'      THEN 1 ELSE 0 END) AS v_pass,
            SUM(CASE WHEN validation_status='fail'      THEN 1 ELSE 0 END) AS v_fail,
            SUM(CASE WHEN validation_status='warn'      THEN 1 ELSE 0 END) AS v_warn,
            SUM(CASE WHEN validation_status='uncertain' THEN 1 ELSE 0 END) AS v_uncertain,
            SUM(CASE WHEN validation_status='skip'      THEN 1 ELSE 0 END) AS v_skip,
            COUNT(*)                                                        AS total
        FROM results
    """).fetchone()

    validated = row["validated"] or 0
    total = row["total"] or 0
    pending = total - validated

    if validated == 0:
        print("No validation results yet")
        return

    evaluable = validated - (row["v_skip"] or 0)
    pass_rate = (row["v_pass"] or 0) / evaluable if evaluable > 0 else 0.0

    print(f"Validation: {validated}/{total} validated ({pending} pending)")
    print(f"  pass={row['v_pass']} fail={row['v_fail']} warn={row['v_warn']} "
          f"uncertain={row['v_uncertain']} skip={row['v_skip']}")
    print(f"  Pass Rate: {pass_rate:.1%}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Response Validation Pipeline (Phase 4a)",
    )
    p.add_argument("--db-path", default=None,
                   help="Path to SQLite DB (default: api/data/llm_tester.db)")
    p.add_argument("--config-path", default=None,
                   help="Path to test_config.json (default: test_config.json)")
    p.add_argument("--run-id", default=None,
                   help="Validate only results from this CI run ID")
    p.add_argument("--dry-run", action="store_true",
                   help="Run validation but don't update DB")
    p.add_argument("--force", action="store_true",
                   help="Re-validate all results (overwrite existing)")
    p.add_argument("--quant-diff", action="store_true",
                   help="Generate quantization diff report")
    p.add_argument("--summary-only", action="store_true",
                   help="Print existing validation stats and exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.db_path:
        global DB_PATH
        DB_PATH = Path(args.db_path)

    config_path = Path(args.config_path) if args.config_path else CONFIG_PATH

    con = get_connection()

    # Summary-only mode
    if args.summary_only:
        print_summary_only(con)
        con.close()
        return

    config = load_config(config_path)

    # Fetch pending results
    rows = fetch_pending(con, args)
    if not rows:
        logger.info("No results to validate")
        if args.quant_diff:
            diffs = compute_all_quant_diffs(con)
            print_quant_report(diffs)
        con.close()
        return

    logger.info("Validating %d results...", len(rows))

    # Run validation
    results: list[ValidationResult] = []
    for row in rows:
        result = validate_row(row, config)
        results.append(result)

    # Update DB
    if not args.dry_run:
        update_validation(con, results)
    else:
        logger.info("Dry run — skipping DB update")

    # Quant diff
    if args.quant_diff:
        diffs = compute_all_quant_diffs(con)
        print_quant_report(diffs)

    # Print summary
    print_validation_summary(results)

    con.close()


if __name__ == "__main__":
    main()