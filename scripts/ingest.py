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
import os
import sqlite3
import sys
from pathlib import Path

# ── 프로젝트 루트 기준 절대경로 (scripts/ 한 단계 위) ─────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

RESULTS_DIR = Path(os.getenv("RESULTS_DIR", str(_PROJECT_ROOT / "results")))
DB_PATH     = Path(os.getenv("DB_PATH",     str(_PROJECT_ROOT / "api" / "data" / "llm_tester.db")))


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
    con.executescript("""
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
    """)
    cols = {row[1] for row in con.execute("PRAGMA table_info(results)")}
    if "run_id" not in cols:
        con.execute("ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id)")
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


# ── runs table ────────────────────────────────────────────────────────────────

def create_run(con: sqlite3.Connection, run_id: str, trigger: str,
               commit_sha: str | None, branch: str | None) -> int:
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

def _float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _str(val, default: str = "") -> str:
    return str(val) if val is not None else default


def parse_result_file(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [WARN] parse error {path}: {e}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(f"  [WARN] unexpected JSON root type in {path}", file=sys.stderr)
        return None

    parts = path.parts
    device_dir = parts[-3] if len(parts) >= 3 else "unknown"
    model_dir  = parts[-2] if len(parts) >= 2 else "unknown"

    # Device — guard: "device" key may be a string in flat JSON
    dev = data.get("device") if isinstance(data.get("device"), dict) else {}
    manufacturer    = _str(dev.get("manufacturer") or data.get("manufacturer") or data.get("device_manufacturer", ""))
    device_model    = _str(dev.get("model")        or data.get("device_model")  or device_dir)
    product         = _str(dev.get("product")      or data.get("product", ""))
    soc             = _str(dev.get("soc")          or data.get("soc", ""))
    android_version = _str(dev.get("android_version") or data.get("android_version", ""))
    sdk_int         = _int(dev.get("sdk_int")      or data.get("sdk_int", 0)) or 0
    cpu_cores       = _int(dev.get("cpu_cores")    or data.get("cpu_cores", 0)) or 0
    max_heap_mb     = _int(dev.get("max_heap_mb")  or data.get("max_heap_mb", 0)) or 0

    # Model — guard: "model" key may be a string in flat JSON
    mdl = data.get("model") if isinstance(data.get("model"), dict) else {}
    model_name = _str(mdl.get("model_name") or data.get("model_name") or model_dir)
    model_path = _str(mdl.get("model_path") or data.get("model_path", ""))
    backend    = _str(mdl.get("backend")    or data.get("backend", ""))

    # Prompt — "prompt" key is a plain string (the prompt text), not a dict
    prm = data.get("prompt_info") if isinstance(data.get("prompt_info"), dict) else {}
    prompt_text_raw = data.get("prompt")
    prompt_text = _str(prompt_text_raw) if not isinstance(prompt_text_raw, dict) else ""
    prompt_id   = _str(prm.get("prompt_id") or data.get("prompt_id") or path.stem)
    # Android app writes "prompt_category" and "prompt_lang" keys in the result JSON
    category    = _str(prm.get("category")  or data.get("prompt_category") or data.get("category", ""))
    lang        = _str(prm.get("lang")      or data.get("prompt_lang")     or data.get("lang", "en"))
    if not prompt_text:
        prompt_text = _str(prm.get("prompt_text") or data.get("prompt_text", ""))

    status = _str(data.get("status", "error"))
    if status not in ("success", "error"):
        status = "error"

    # ── Metrics: nested "metrics" dict 우선, flat fallback (구버전 PoC 호환) ──
    met = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}

    return {
        "manufacturer":    manufacturer,
        "device_model":    device_model,
        "product":         product,
        "soc":             soc,
        "android_version": android_version,
        "sdk_int":         sdk_int,
        "cpu_cores":       cpu_cores,
        "max_heap_mb":     max_heap_mb,
        "model_name":      model_name,
        "model_path":      model_path,
        "backend":         backend,
        "prompt_id":       prompt_id,
        "category":        category,
        "lang":            lang,
        "prompt_text":     prompt_text,
        "status":          status,
        "latency_ms":            _float(data.get("latency_ms")),
        "init_time_ms":          _float(data.get("init_time_ms")),
        "response":              _str(data.get("response")),
        "error":                 data.get("error"),
        "ttft_ms":               _float(met.get("ttft_ms")               or data.get("ttft_ms")),
        "prefill_time_ms":       _float(met.get("prefill_time_ms")       or data.get("prefill_time_ms")),
        "decode_time_ms":        _float(met.get("decode_time_ms")        or data.get("decode_time_ms")),
        "input_token_count":     _int(met.get("input_token_count")       or data.get("input_token_count")),
        "output_token_count":    _int(met.get("output_token_count")      or data.get("output_token_count")),
        "prefill_tps":           _float(met.get("prefill_tps")           or data.get("prefill_tps")),
        "decode_tps":            _float(met.get("decode_tps")            or data.get("decode_tps")),
        "peak_java_memory_mb":   _float(met.get("peak_java_memory_mb")   or data.get("peak_java_memory_mb")),
        "peak_native_memory_mb": _float(met.get("peak_native_memory_mb") or data.get("peak_native_memory_mb")),
        "itl_p50_ms":            _float(met.get("itl_p50_ms")            or data.get("itl_p50_ms")),
        "itl_p95_ms":            _float(met.get("itl_p95_ms")            or data.get("itl_p95_ms")),
        "itl_p99_ms":            _float(met.get("itl_p99_ms")            or data.get("itl_p99_ms")),
        "timestamp":             _int(data.get("timestamp")),
    }


# ── Core ingest ───────────────────────────────────────────────────────────────

def ingest(con: sqlite3.Connection, run_pk: int | None) -> tuple[int, int, int]:
    inserted = skipped = errors = 0

    json_files = list(RESULTS_DIR.rglob("*.json"))
    if not json_files:
        print(f"No JSON files found in {RESULTS_DIR}", file=sys.stderr)
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
            print(f"  [ERROR] insert failed for {path}: {e}", file=sys.stderr)
            errors += 1
            con.rollback()
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
    errors  = row[2] or 0

    run_row = con.execute("""
        SELECT run_id, trigger, branch, started_at, status
        FROM runs ORDER BY id DESC LIMIT 1
    """).fetchone()

    print(f"Total results in DB : {total}")
    print(f"  success           : {success}")
    print(f"  error             : {errors}")
    if run_row:
        print(f"Latest run          : {run_row['run_id']} ({run_row['trigger']}) "
              f"branch={run_row['branch']} started={run_row['started_at']} status={run_row['status']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ingest JSON results into SQLite DB")
    p.add_argument("--results-dir", default=None)
    p.add_argument("--db-path", default=None)
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

    con = get_connection()
    init_tables(con)

    if args.summary_only:
        print_summary(con)
        con.close()
        return

    run_pk: int | None = None
    if args.run_id:
        run_pk = create_run(con, args.run_id, args.trigger, args.commit_sha, args.branch)
        print(f"[run] started  run_id={args.run_id} trigger={args.trigger} "
              f"branch={args.branch} commit={args.commit_sha}")

    try:
        inserted, skipped, errors = ingest(con, run_pk)
    except Exception as e:
        if run_pk is not None:
            finalize_run(con, run_pk, "error")
        con.close()
        print(f"[FATAL] ingest failed: {e}", file=sys.stderr)
        sys.exit(1)

    if run_pk is not None:
        status = "error" if errors and not inserted else "success"
        finalize_run(con, run_pk, status)
        print(f"[run] finished run_id={args.run_id} status={status}")

    print(f"\nIngest complete — inserted: {inserted}, skipped: {skipped}, errors: {errors}")
    con.close()


if __name__ == "__main__":
    main()