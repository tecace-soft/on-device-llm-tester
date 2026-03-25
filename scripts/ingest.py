"""
ingest.py — JSON → SQLite 적재 스크립트 (Phase 2 CI/CD 확장)

Usage:
    # 기존 (하위 호환)
    python scripts/ingest.py

    # Phase 2 CI 실행 시
    python scripts/ingest.py \
        --run-id 12345678 \
        --trigger manual \
        --commit-sha abc123def \
        --branch main

    # GitHub Actions Summary 출력용
    python scripts/ingest.py --summary-only
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── 프로젝트 루트 기준 절대경로 (scripts/ 한 단계 위) ─────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

RESULTS_DIR = Path(os.getenv("RESULTS_DIR", str(_PROJECT_ROOT / "results")))
DB_PATH     = Path(os.getenv("DB_PATH",     str(_PROJECT_ROOT / "api" / "data" / "llm_tester.db")))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", str(_PROJECT_ROOT / "test_config.json")))


# ── Shared DDL (single source of truth) ───────────────────────────────────────
# NOTE: This DDL is intentionally duplicated from api/db.py for sync-driver usage.
#       If you modify the schema, update BOTH files.
#       TODO: Extract to a shared db_schema.py module.

_DDL = """
CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer    TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    product         TEXT NOT NULL DEFAULT '',
    soc             TEXT NOT NULL DEFAULT '',
    android_version TEXT NOT NULL DEFAULT '',
    sdk_int         INTEGER NOT NULL DEFAULT 0,
    cpu_cores       INTEGER NOT NULL DEFAULT 0,
    max_heap_mb     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(manufacturer, model, product)
);

CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name  TEXT NOT NULL DEFAULT '',
    model_path  TEXT NOT NULL DEFAULT '',
    backend     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model_name, model_path, backend)
);

CREATE TABLE IF NOT EXISTS prompts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id   TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL DEFAULT '',
    lang        TEXT NOT NULL DEFAULT 'en',
    prompt_text TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL UNIQUE,
    trigger     TEXT NOT NULL DEFAULT '',
    commit_sha  TEXT,
    branch      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id),
    model_id      INTEGER NOT NULL REFERENCES models(id),
    prompt_id     INTEGER NOT NULL REFERENCES prompts(id),
    run_id        INTEGER REFERENCES runs(id),

    status        TEXT NOT NULL CHECK(status IN ('success', 'error')),
    latency_ms    REAL,
    init_time_ms  REAL,

    response      TEXT NOT NULL DEFAULT '',
    error         TEXT,

    ttft_ms               REAL,
    prefill_time_ms       REAL,
    decode_time_ms        REAL,
    input_token_count     INTEGER,
    output_token_count    INTEGER,
    prefill_tps           REAL,
    decode_tps            REAL,
    peak_java_memory_mb   REAL,
    peak_native_memory_mb REAL,
    itl_p50_ms            REAL,
    itl_p95_ms            REAL,
    itl_p99_ms            REAL,

    timestamp  INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(device_id, model_id, prompt_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_results_status    ON results(status);
CREATE INDEX IF NOT EXISTS idx_results_device    ON results(device_id);
CREATE INDEX IF NOT EXISTS idx_results_model     ON results(model_id);
CREATE INDEX IF NOT EXISTS idx_results_prompt    ON results(prompt_id);
CREATE INDEX IF NOT EXISTS idx_results_run       ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_timestamp ON results(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_results_filter    ON results(device_id, model_id, status);
"""


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def init_tables(con: sqlite3.Connection) -> None:
    con.executescript(_DDL)

    # Phase 2 migration: run_id on results
    cols = {row[1] for row in con.execute("PRAGMA table_info(results)")}
    if "run_id" not in cols:
        con.execute("ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id)")

    # Phase 4a migration: validation columns on results
    if "validation_status" not in cols:
        con.execute("ALTER TABLE results ADD COLUMN validation_status TEXT")
    if "validation_detail" not in cols:
        con.execute("ALTER TABLE results ADD COLUMN validation_detail TEXT")

    # Phase 4a migration: ground_truth, eval_strategy on prompts
    prompt_cols = {row[1] for row in con.execute("PRAGMA table_info(prompts)")}
    if "ground_truth" not in prompt_cols:
        con.execute("ALTER TABLE prompts ADD COLUMN ground_truth TEXT")
    if "eval_strategy" not in prompt_cols:
        con.execute("ALTER TABLE prompts ADD COLUMN eval_strategy TEXT NOT NULL DEFAULT 'none'")

    con.commit()


# ── Dimension upserts ─────────────────────────────────────────────────────────

def upsert_device(con: sqlite3.Connection, manufacturer: str, model: str, product: str,
                  soc: str, android_version: str, sdk_int: int,
                  cpu_cores: int, max_heap_mb: int) -> int:
    con.execute("""
        INSERT OR IGNORE INTO devices
            (manufacturer, model, product, soc, android_version, sdk_int, cpu_cores, max_heap_mb)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (manufacturer, model, product, soc, android_version, sdk_int, cpu_cores, max_heap_mb))
    row = con.execute(
        "SELECT id FROM devices WHERE manufacturer=? AND model=? AND product=?",
        (manufacturer, model, product),
    ).fetchone()
    return row[0]


def upsert_model(con: sqlite3.Connection, model_name: str, model_path: str, backend: str) -> int:
    con.execute("""
        INSERT OR IGNORE INTO models (model_name, model_path, backend)
        VALUES (?, ?, ?)
    """, (model_name, model_path, backend))
    row = con.execute(
        "SELECT id FROM models WHERE model_name=? AND model_path=? AND backend=?",
        (model_name, model_path, backend),
    ).fetchone()
    return row[0]


def upsert_prompt(con: sqlite3.Connection, prompt_id: str, category: str,
                  lang: str, prompt_text: str) -> int:
    con.execute("""
        INSERT OR IGNORE INTO prompts (prompt_id, category, lang, prompt_text)
        VALUES (?, ?, ?, ?)
    """, (prompt_id, category, lang, prompt_text))
    row = con.execute("SELECT id FROM prompts WHERE prompt_id=?", (prompt_id,)).fetchone()
    return row[0]


# ── Phase 4a: ground_truth / eval_strategy sync from test_config.json ─────────

def _load_config_prompt_map(config_path: Path) -> dict[str, dict]:
    """Load test_config.json and return {prompt_id: {ground_truth, eval_strategy}}."""
    if not config_path.exists():
        logger.warning("Config file not found: %s — skipping ground_truth sync", config_path)
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Config parse failed: %s — skipping ground_truth sync", e)
        return {}

    result = {}
    for p in config.get("prompts", []):
        pid = p.get("id")
        if pid:
            result[pid] = {
                "ground_truth": p.get("ground_truth"),
                "eval_strategy": p.get("eval_strategy", "none"),
            }
    return result


def sync_ground_truth(con: sqlite3.Connection, config_path: Path) -> int:
    """Update prompts table with ground_truth and eval_strategy from test_config.json.

    Returns number of prompts updated.
    """
    prompt_map = _load_config_prompt_map(config_path)
    if not prompt_map:
        return 0

    updated = 0
    for prompt_id, vals in prompt_map.items():
        ground_truth = vals["ground_truth"]
        eval_strategy = vals["eval_strategy"]

        # Validate eval_strategy
        valid_strategies = {"deterministic", "deterministic_with_fallback", "structural", "none"}
        if eval_strategy not in valid_strategies:
            logger.warning("Unknown eval_strategy '%s' for prompt '%s' — falling back to 'none'",
                           eval_strategy, prompt_id)
            eval_strategy = "none"

        cur = con.execute("""
            UPDATE prompts
            SET ground_truth = ?, eval_strategy = ?
            WHERE prompt_id = ?
        """, (ground_truth, eval_strategy, prompt_id))
        if cur.rowcount:
            updated += 1

    con.commit()
    logger.info("Ground truth synced: %d prompts updated from %s", updated, config_path)
    return updated


# ── runs table ────────────────────────────────────────────────────────────────

def create_run(con: sqlite3.Connection, run_id: str, trigger: str,
               commit_sha: Optional[str], branch: Optional[str]) -> int:
    con.execute("""
        INSERT OR IGNORE INTO runs (run_id, trigger, commit_sha, branch, started_at, status)
        VALUES (?, ?, ?, ?, datetime('now'), 'running')
    """, (run_id, trigger, commit_sha, branch))
    con.commit()
    row = con.execute("SELECT id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return row[0]


def finalize_run(con: sqlite3.Connection, run_pk: int, status: str) -> None:
    con.execute("""
        UPDATE runs SET finished_at = datetime('now'), status = ?
        WHERE id = ?
    """, (status, run_pk))
    con.commit()


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int(v: object) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def parse_result_file(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("JSON parse failed for %s: %s", path, e)
        return None

    device = data.get("device") or {}
    met = data.get("metrics") or {}

    model_path = data.get("model_path", "")
    model_name = data.get("model_name", "")
    if not model_name and model_path:
        model_name = os.path.basename(model_path)

    return {
        "manufacturer":          device.get("manufacturer", ""),
        "device_model":          device.get("model", ""),
        "product":               device.get("product", ""),
        "soc":                   device.get("soc", ""),
        "android_version":       device.get("android_version", ""),
        "sdk_int":               _int(device.get("sdk_int")) or 0,
        "cpu_cores":             _int(device.get("cpu_cores")) or 0,
        "max_heap_mb":           _int(device.get("max_heap_mb")) or 0,
        "model_name":            model_name,
        "model_path":            model_path,
        "backend":               (data.get("backend") or "CPU").upper(),
        "prompt_id":             data.get("prompt_id", "unknown"),
        "category":              data.get("prompt_category", ""),
        "lang":                  data.get("prompt_lang", "en"),
        "prompt_text":           data.get("prompt", ""),
        "status":                data.get("status", "error"),
        "latency_ms":            _float(data.get("latency_ms")),
        "init_time_ms":          _float(data.get("init_time_ms")),
        "response":              data.get("response", ""),
        "error":                 data.get("error"),
        "ttft_ms":               _float(met.get("ttft_ms")              or data.get("ttft_ms")),
        "prefill_time_ms":       _float(met.get("prefill_time_ms")      or data.get("prefill_time_ms")),
        "decode_time_ms":        _float(met.get("decode_time_ms")       or data.get("decode_time_ms")),
        "input_token_count":     _int(met.get("input_token_count")      or data.get("input_token_count")),
        "output_token_count":    _int(met.get("output_token_count")     or data.get("output_token_count")),
        "prefill_tps":           _float(met.get("prefill_tps")          or data.get("prefill_tps")),
        "decode_tps":            _float(met.get("decode_tps")           or data.get("decode_tps")),
        "peak_java_memory_mb":   _float(met.get("peak_java_memory_mb")  or data.get("peak_java_memory_mb")),
        "peak_native_memory_mb": _float(met.get("peak_native_memory_mb") or data.get("peak_native_memory_mb")),
        "itl_p50_ms":            _float(met.get("itl_p50_ms")           or data.get("itl_p50_ms")),
        "itl_p95_ms":            _float(met.get("itl_p95_ms")           or data.get("itl_p95_ms")),
        "itl_p99_ms":            _float(met.get("itl_p99_ms")           or data.get("itl_p99_ms")),
        "timestamp":             _int(data.get("timestamp")),
    }


# ── Core ingest ───────────────────────────────────────────────────────────────
# FIX(P2): Previous version used con.rollback() inside the per-record loop,
# which rolled back ALL previously inserted records in the same transaction.
# Now we use autocommit=False and commit in batches. Individual INSERT OR IGNORE
# failures are caught without rolling back the entire batch.

def ingest(con: sqlite3.Connection, run_pk: Optional[int]) -> tuple[int, int, int]:
    inserted = skipped = errors = 0

    json_files = list(RESULTS_DIR.rglob("*.json"))
    if not json_files:
        logger.warning("No JSON files found in %s", RESULTS_DIR)
        return inserted, skipped, errors

    for path in sorted(json_files):
        rec = parse_result_file(path)
        if rec is None:
            errors += 1
            continue

        try:
            device_pk = upsert_device(
                con,
                rec["manufacturer"], rec["device_model"], rec["product"],
                rec["soc"], rec["android_version"],
                rec["sdk_int"], rec["cpu_cores"], rec["max_heap_mb"],
            )
            model_pk  = upsert_model(con, rec["model_name"], rec["model_path"], rec["backend"])
            prompt_pk = upsert_prompt(con, rec["prompt_id"], rec["category"], rec["lang"], rec["prompt_text"])

            cur = con.execute("""
                INSERT OR IGNORE INTO results (
                    device_id, model_id, prompt_id, run_id,
                    status, latency_ms, init_time_ms, response, error,
                    ttft_ms, prefill_time_ms, decode_time_ms,
                    input_token_count, output_token_count,
                    prefill_tps, decode_tps,
                    peak_java_memory_mb, peak_native_memory_mb,
                    itl_p50_ms, itl_p95_ms, itl_p99_ms,
                    timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device_pk, model_pk, prompt_pk, run_pk,
                rec["status"], rec["latency_ms"], rec["init_time_ms"],
                rec["response"], rec["error"],
                rec["ttft_ms"], rec["prefill_time_ms"], rec["decode_time_ms"],
                rec["input_token_count"], rec["output_token_count"],
                rec["prefill_tps"], rec["decode_tps"],
                rec["peak_java_memory_mb"], rec["peak_native_memory_mb"],
                rec["itl_p50_ms"], rec["itl_p95_ms"], rec["itl_p99_ms"],
                rec["timestamp"],
            ))
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            # FIX(P2): Do NOT call con.rollback() here.
            # INSERT OR IGNORE handles UNIQUE violations gracefully.
            # Other errors (e.g. CHECK constraint) are logged and skipped
            # without destroying previously successful inserts in this batch.
            logger.error("Insert failed for %s: %s", path, e)
            errors += 1
            continue

    con.commit()
    return inserted, skipped, errors


# ── Summary-only mode ─────────────────────────────────────────────────────────

def print_summary(con: sqlite3.Connection) -> None:
    row = con.execute("""
        SELECT
            COUNT(*)                                    AS total,
            SUM(CASE WHEN status='success' THEN 1 END) AS success,
            SUM(CASE WHEN status='error'   THEN 1 END) AS errors
        FROM results
    """).fetchone()
    total   = row[0] or 0
    success = row[1] or 0
    errs    = row[2] or 0

    run_row = con.execute("""
        SELECT run_id, trigger, branch, started_at, status
        FROM runs ORDER BY id DESC LIMIT 1
    """).fetchone()

    print(f"Total results in DB : {total}")
    print(f"  success           : {success}")
    print(f"  error             : {errs}")
    if run_row:
        print(f"Latest run          : {run_row['run_id']} ({run_row['trigger']}) "
              f"branch={run_row['branch']} started={run_row['started_at']} status={run_row['status']}")

    # Phase 4a: validation summary
    val_row = con.execute("""
        SELECT
            COUNT(validation_status)                                        AS validated,
            SUM(CASE WHEN validation_status='pass'      THEN 1 ELSE 0 END) AS v_pass,
            SUM(CASE WHEN validation_status='fail'      THEN 1 ELSE 0 END) AS v_fail,
            SUM(CASE WHEN validation_status='warn'      THEN 1 ELSE 0 END) AS v_warn,
            SUM(CASE WHEN validation_status='uncertain' THEN 1 ELSE 0 END) AS v_uncertain,
            SUM(CASE WHEN validation_status='skip'      THEN 1 ELSE 0 END) AS v_skip
        FROM results
    """).fetchone()
    validated = val_row[0] or 0
    if validated > 0:
        print(f"Validation          : {validated} validated "
              f"(pass={val_row[1]}, fail={val_row[2]}, warn={val_row[3]}, "
              f"uncertain={val_row[4]}, skip={val_row[5]})")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ingest JSON results into SQLite DB")
    p.add_argument("--results-dir", default=None)
    p.add_argument("--db-path", default=None)
    p.add_argument("--config-path", default=None,
                   help="Path to test_config.json for ground_truth sync")
    p.add_argument("--run-id", default=None)
    p.add_argument("--trigger", default="manual")
    p.add_argument("--commit-sha", default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--summary-only", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()

    if args.results_dir:
        global RESULTS_DIR
        RESULTS_DIR = Path(args.results_dir)
    if args.db_path:
        global DB_PATH
        DB_PATH = Path(args.db_path)

    config_path = Path(args.config_path) if args.config_path else CONFIG_PATH

    con = get_connection()
    init_tables(con)

    if args.summary_only:
        print_summary(con)
        con.close()
        return

    run_pk: Optional[int] = None
    if args.run_id:
        run_pk = create_run(con, args.run_id, args.trigger, args.commit_sha, args.branch)
        logger.info("Run started  run_id=%s trigger=%s branch=%s commit=%s",
                     args.run_id, args.trigger, args.branch, args.commit_sha)

    try:
        inserted, skipped, errors = ingest(con, run_pk)
    except Exception as e:
        if run_pk is not None:
            finalize_run(con, run_pk, "error")
        con.close()
        logger.fatal("Ingest failed: %s", e)
        sys.exit(1)

    # Phase 4a: sync ground_truth + eval_strategy from test_config.json
    gt_updated = sync_ground_truth(con, config_path)

    if run_pk is not None:
        # FIX(H): Mark as error if nothing was inserted (phantom run prevention)
        if inserted == 0 and errors == 0 and skipped == 0:
            status = "error"
        elif errors and not inserted:
            status = "error"
        else:
            status = "success"
        finalize_run(con, run_pk, status)
        logger.info("Run finished run_id=%s status=%s", args.run_id, status)

    print(f"\nIngest complete — inserted: {inserted}, skipped: {skipped}, errors: {errors}")
    if gt_updated:
        print(f"Ground truth synced: {gt_updated} prompts")
    con.close()


if __name__ == "__main__":
    main()