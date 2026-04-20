"""
ingest.py — JSON → SQLite/Turso 적재 스크립트 (Phase 7 Cloud Deployment)

Architecture: DEPLOYMENT_ARCHITECTURE.md §5

Usage:
    # 기존 (하위 호환 — 로컬 SQLite)
    python scripts/ingest.py

    # Phase 2 CI 실행 시 (로컬 SQLite)
    python scripts/ingest.py \
        --run-id 12345678 \
        --trigger manual \
        --commit-sha abc123def \
        --branch main

    # Phase 7: Turso 클라우드 적재
    DB_MODE=turso python scripts/ingest.py \
        --run-id 12345678 \
        --trigger manual \
        --commit-sha abc123def \
        --branch main

    # GitHub Actions Summary 출력용
    python scripts/ingest.py --summary-only
"""

import argparse
import base64 as _base64
import json
import logging
import os
import sqlite3
import sys
import urllib.request as _urllib_request
from pathlib import Path
from typing import Any, Optional

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

# Phase 6: profile JSON 매칭 시 허용하는 타임스탬프 차이 (ms)
_PROFILE_MATCH_WINDOW_MS = 5000

# Phase 7: Turso Batch INSERT 크기 (DEPLOYMENT_ARCHITECTURE.md §5.2)
BATCH_SIZE = 100

# Phase 7: DB 모드 — "local" (기존 SQLite) | "turso" (클라우드)
DB_MODE = os.getenv("DB_MODE", "local")


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
    engine      TEXT NOT NULL DEFAULT 'mediapipe',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model_name, model_path, backend, engine)
);

CREATE TABLE IF NOT EXISTS prompts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id     TEXT NOT NULL UNIQUE,
    category      TEXT NOT NULL DEFAULT '',
    lang          TEXT NOT NULL DEFAULT 'en',
    prompt_text   TEXT NOT NULL DEFAULT '',
    ground_truth  TEXT,
    eval_strategy TEXT NOT NULL DEFAULT 'none',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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

    -- Phase 6: Resource profiling columns
    battery_level_start   INTEGER,
    battery_level_end     INTEGER,
    thermal_start         INTEGER,
    thermal_end           INTEGER,
    voltage_start_mv      INTEGER,
    voltage_end_mv        INTEGER,
    current_before_ua     INTEGER,
    current_after_ua      INTEGER,
    system_pss_mb         REAL,
    profiling_error       TEXT,

    -- Phase 4a: Response validation columns
    validation_status     TEXT,
    validation_detail     TEXT,

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


# ── DB helpers (LOCAL — 기존 코드 보존) ───────────────────────────────────────

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

    # Phase 5 migration: engine column on models
    model_cols = {row[1] for row in con.execute("PRAGMA table_info(models)")}
    if "engine" not in model_cols:
        con.execute("ALTER TABLE models ADD COLUMN engine TEXT NOT NULL DEFAULT 'mediapipe'")
        logger.info("Phase 5 migration: added 'engine' column to models table")

    # Phase 6 migration: resource profiling columns on results
    phase6_cols = {
        "battery_level_start": "INTEGER",
        "battery_level_end": "INTEGER",
        "thermal_start": "INTEGER",
        "thermal_end": "INTEGER",
        "voltage_start_mv": "INTEGER",
        "voltage_end_mv": "INTEGER",
        "current_before_ua": "INTEGER",
        "current_after_ua": "INTEGER",
        "system_pss_mb": "REAL",
        "profiling_error": "TEXT",
    }
    added = []
    for col_name, col_type in phase6_cols.items():
        if col_name not in cols:
            con.execute(f"ALTER TABLE results ADD COLUMN {col_name} {col_type}")
            added.append(col_name)
    if added:
        logger.info("Phase 6 migration: added %d resource profiling columns (%s)",
                     len(added), ", ".join(added))

    con.commit()


# ── Dimension upserts (LOCAL) ─────────────────────────────────────────────────

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


def upsert_model(con: sqlite3.Connection, model_name: str, model_path: str,
                 backend: str, engine: str = "mediapipe") -> int:
    con.execute("""
        INSERT OR IGNORE INTO models (model_name, model_path, backend, engine)
        VALUES (?, ?, ?, ?)
    """, (model_name, model_path, backend, engine))
    row = con.execute(
        "SELECT id FROM models WHERE model_name=? AND model_path=? AND backend=? AND engine=?",
        (model_name, model_path, backend, engine),
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


# ── runs table (LOCAL) ────────────────────────────────────────────────────────

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

def _float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _is_profile_json(data: dict) -> bool:
    """Phase 6: profile_*.json인지 판별. type=resource_profile이면 True."""
    return data.get("type") == "resource_profile"


def _find_matching_profile(result_path: Path, timestamp: Optional[int]) -> Optional[dict]:
    """Phase 6: 결과 JSON과 매칭되는 profile JSON 검색.

    같은 디렉토리에서 profile_*.json 중 timestamp 차이가 ±5초 이내인 것을 찾음.
    추가 매칭 기준: prompt_id + model_name (동시에 여러 테스트가 진행될 때 안전)
    """
    if timestamp is None:
        return None

    result_dir = result_path.parent
    for profile_path in result_dir.glob("profile_*.json"):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                profile = json.load(f)
            if profile.get("type") != "resource_profile":
                continue
            p_ts = profile.get("timestamp", 0)
            if abs(p_ts - timestamp) <= _PROFILE_MATCH_WINDOW_MS:
                return profile
        except (json.JSONDecodeError, OSError):
            continue
    return None


def parse_result_file(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("JSON parse failed for %s: %s", path, e)
        return None

    # Phase 6: profile JSON은 적재 대상이 아님 (result와 매칭하여 merge)
    if _is_profile_json(data):
        return None

    device = data.get("device") or {}
    met = data.get("metrics") or {}

    model_path = data.get("model_path", "")
    model_name = data.get("model_name", "")
    if not model_name and model_path:
        model_name = os.path.basename(model_path)

    # Phase 5: engine field (default to mediapipe for backward compat)
    engine = data.get("engine", "mediapipe")

    timestamp = _int(data.get("timestamp"))

    # Phase 6: profiling 데이터 수집
    # 1. 에러 JSON에는 profiling 데이터가 직접 포함됨 (runner.py가 merge)
    # 2. 성공 JSON에는 없으므로 별도 profile_*.json에서 매칭
    profile_data = _extract_profile_from_data(data)
    if not _has_profiling(profile_data):
        matched_profile = _find_matching_profile(path, timestamp)
        if matched_profile:
            profile_data = _extract_profile_from_data(matched_profile)
            logger.debug("[PROFILE:MATCH] %s matched with profile JSON", path.name)

    rec = {
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
        "engine":                engine,
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
        "timestamp":             timestamp,
    }

    rec.update(profile_data)
    return rec


def _extract_profile_from_data(data: dict) -> dict:
    """Phase 6: JSON data에서 profiling 필드 추출. 없으면 전부 None."""
    return {
        "battery_level_start":  _int(data.get("battery_level_start")),
        "battery_level_end":    _int(data.get("battery_level_end")),
        "thermal_start":        _int(data.get("thermal_start")),
        "thermal_end":          _int(data.get("thermal_end")),
        "voltage_start_mv":     _int(data.get("voltage_start_mv")),
        "voltage_end_mv":       _int(data.get("voltage_end_mv")),
        "current_before_ua":    _int(data.get("current_before_ua")),
        "current_after_ua":     _int(data.get("current_after_ua")),
        "system_pss_mb":        _float(data.get("system_pss_mb")),
        "profiling_error":      data.get("profiling_error"),
    }


def _has_profiling(profile_data: dict) -> bool:
    """Phase 6: profiling 데이터가 하나라도 있는지 확인."""
    for key in ("battery_level_start", "thermal_start", "voltage_start_mv", "system_pss_mb"):
        if profile_data.get(key) is not None:
            return True
    return False


# ── Core ingest (LOCAL — 기존 코드 보존) ──────────────────────────────────────
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
            # Phase 6: profile_*.json은 None 반환 → skip (에러 아님)
            if path.name.startswith("profile_"):
                skipped += 1
            else:
                errors += 1
            continue

        try:
            device_pk = upsert_device(
                con,
                rec["manufacturer"], rec["device_model"], rec["product"],
                rec["soc"], rec["android_version"],
                rec["sdk_int"], rec["cpu_cores"], rec["max_heap_mb"],
            )
            model_pk  = upsert_model(con, rec["model_name"], rec["model_path"],
                                     rec["backend"], rec["engine"])
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
                    battery_level_start, battery_level_end,
                    thermal_start, thermal_end,
                    voltage_start_mv, voltage_end_mv,
                    current_before_ua, current_after_ua,
                    system_pss_mb, profiling_error,
                    timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device_pk, model_pk, prompt_pk, run_pk,
                rec["status"], rec["latency_ms"], rec["init_time_ms"],
                rec["response"], rec["error"],
                rec["ttft_ms"], rec["prefill_time_ms"], rec["decode_time_ms"],
                rec["input_token_count"], rec["output_token_count"],
                rec["prefill_tps"], rec["decode_tps"],
                rec["peak_java_memory_mb"], rec["peak_native_memory_mb"],
                rec["itl_p50_ms"], rec["itl_p95_ms"], rec["itl_p99_ms"],
                rec["battery_level_start"], rec["battery_level_end"],
                rec["thermal_start"], rec["thermal_end"],
                rec["voltage_start_mv"], rec["voltage_end_mv"],
                rec["current_before_ua"], rec["current_after_ua"],
                rec["system_pss_mb"], rec["profiling_error"],
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


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7: TURSO MODE — Dual-mode Batch INSERT
# Architecture: DEPLOYMENT_ARCHITECTURE.md §5
# ══════════════════════════════════════════════════════════════════════════════

# ── Turso HTTP v2 sync client ─────────────────────────────────────────────────
# Replaces libsql-client (WebSocket/wss://) which returns HTTP 505 on Turso.
# Uses stdlib urllib to POST against Turso's /v2/pipeline endpoint.


class _TursoStatement:
    """Mirrors libsql_client.Statement for drop-in compatibility."""

    __slots__ = ("sql", "args")

    def __init__(self, sql: str, args: Optional[list] = None) -> None:
        self.sql = sql
        self.args = args or []


class _TursoResultSet:
    """Mirrors libsql_client.ResultSet — exposes .rows and .rows_affected."""

    __slots__ = ("columns", "rows", "rows_affected", "last_insert_rowid")

    def __init__(
        self,
        columns: Optional[list] = None,
        rows: Optional[list] = None,
        rows_affected: int = 0,
        last_insert_rowid: Optional[int] = None,
    ) -> None:
        self.columns = columns or []
        self.rows = rows or []
        self.rows_affected = rows_affected
        self.last_insert_rowid = last_insert_rowid


def _turso_encode(v: Any) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": _base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _turso_decode(cell: dict) -> Any:
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        return _base64.b64decode(cell.get("base64", ""))
    return cell.get("value", "")


class _TursoSyncClient:
    """Synchronous Turso client over HTTP v2 pipeline.

    Why: libsql-client uses WebSocket (wss://) which returns HTTP 505 on Turso.
    Used by: _get_turso_client()
    """

    def __init__(self, url: str, token: str) -> None:
        self._url = url.replace("libsql://", "https://") + "/v2/pipeline"
        self._token = token

    def _pipeline(self, stmts: list) -> list:
        reqs: list = []
        for s in stmts:
            if isinstance(s, _TursoStatement):
                sql, args = s.sql, s.args
            elif isinstance(s, str):
                sql, args = s, []
            else:
                sql, args = s[0], (s[1] if len(s) > 1 else [])
            reqs.append({"type": "execute", "stmt": {
                "sql": sql,
                "args": [_turso_encode(a) for a in (args or [])],
            }})
        reqs.append({"type": "close"})

        body = json.dumps({"requests": reqs}).encode()
        req = _urllib_request.Request(
            self._url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        with _urllib_request.urlopen(req) as resp:
            data = json.loads(resp.read())

        results: list = []
        for entry in data.get("results", []):
            if entry.get("type") == "error":
                err = entry.get("error", {})
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"Turso pipeline error: {msg}")
            if entry.get("type") != "ok":
                continue
            resp_body = entry.get("response", {})
            if resp_body.get("type") != "execute":
                continue
            result = resp_body.get("result") or {}
            cols = [c.get("name", "") for c in result.get("cols") or []]
            rows = [
                [_turso_decode(cell) for cell in row]
                for row in (result.get("rows") or [])
            ]
            affected = int(result.get("affected_row_count") or 0)
            last_id = result.get("last_insert_rowid")
            results.append(_TursoResultSet(
                columns=cols,
                rows=rows,
                rows_affected=affected,
                last_insert_rowid=int(last_id) if last_id is not None else None,
            ))
        return results

    def execute(self, sql: str, args: Optional[list] = None) -> _TursoResultSet:
        rs = self._pipeline([_TursoStatement(sql, args or [])])
        return rs[0] if rs else _TursoResultSet()

    def batch(self, stmts: list) -> list:
        return self._pipeline(stmts)

    def close(self) -> None:
        pass


def _get_turso_client() -> _TursoSyncClient:
    """Create a synchronous Turso HTTP v2 client.

    Used by: main() when DB_MODE=turso
    """
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    if not url or not token:
        logger.error("TURSO_URL and TURSO_AUTH_TOKEN must be set when DB_MODE=turso")
        sys.exit(1)

    return _TursoSyncClient(url=url, token=token)


def init_tables_turso(client) -> None:
    """Execute DDL on Turso via batch. Turso manages WAL/FK internally.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5.3
    Used by: main() turso branch
    """
    statements = [s.strip() for s in _DDL.split(";") if s.strip()]
    batch = [_TursoStatement(s) for s in statements]
    client.batch(batch)
    logger.info("Turso: DDL init complete (%d statements)", len(batch))

    # Migration for pre-existing Turso DBs created before schema additions.
    # Why: CREATE TABLE IF NOT EXISTS does not add columns to existing tables.
    # Mirrors init_tables() local migrations so Turso stays in sync.
    _migrate_turso_schema(client)


def _migrate_turso_schema(client) -> None:
    """Add missing columns to existing Turso tables via ALTER TABLE.

    Used by: init_tables_turso()
    """
    def _existing_cols(table: str) -> set:
        rs = client.execute(f"PRAGMA table_info({table})")
        # PRAGMA table_info returns rows: (cid, name, type, notnull, dflt_value, pk)
        return {row[1] for row in rs.rows}

    # prompts: Phase 4a (ground_truth, eval_strategy)
    prompt_cols = _existing_cols("prompts")
    prompt_migrations = []
    if "ground_truth" not in prompt_cols:
        prompt_migrations.append("ALTER TABLE prompts ADD COLUMN ground_truth TEXT")
    if "eval_strategy" not in prompt_cols:
        prompt_migrations.append(
            "ALTER TABLE prompts ADD COLUMN eval_strategy TEXT NOT NULL DEFAULT 'none'"
        )

    # results: Phase 2 (run_id), Phase 4a (validation_*), Phase 6 (profiling)
    result_cols = _existing_cols("results")
    result_migrations = []
    if "run_id" not in result_cols:
        result_migrations.append(
            "ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id)"
        )
    if "validation_status" not in result_cols:
        result_migrations.append("ALTER TABLE results ADD COLUMN validation_status TEXT")
    if "validation_detail" not in result_cols:
        result_migrations.append("ALTER TABLE results ADD COLUMN validation_detail TEXT")

    phase6_cols = {
        "battery_level_start": "INTEGER",
        "battery_level_end":   "INTEGER",
        "thermal_start":       "INTEGER",
        "thermal_end":         "INTEGER",
        "voltage_start_mv":    "INTEGER",
        "voltage_end_mv":      "INTEGER",
        "current_before_ua":   "INTEGER",
        "current_after_ua":    "INTEGER",
        "system_pss_mb":       "REAL",
        "profiling_error":     "TEXT",
    }
    for col_name, col_type in phase6_cols.items():
        if col_name not in result_cols:
            result_migrations.append(
                f"ALTER TABLE results ADD COLUMN {col_name} {col_type}"
            )

    # models: Phase 5 (engine)
    model_cols = _existing_cols("models")
    model_migrations = []
    if "engine" not in model_cols:
        model_migrations.append(
            "ALTER TABLE models ADD COLUMN engine TEXT NOT NULL DEFAULT 'mediapipe'"
        )

    all_migrations = prompt_migrations + result_migrations + model_migrations
    if not all_migrations:
        logger.info("Turso: schema is up to date (no migrations needed)")
        return

    # Execute one by one; an individual failure (e.g. racing init) shouldn't
    # abort the rest.
    applied = 0
    for sql in all_migrations:
        try:
            client.execute(sql)
            applied += 1
        except Exception as e:
            # "duplicate column" means another client migrated first — tolerable.
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                continue
            logger.warning("Turso migration failed (%s): %s", sql, e)
    logger.info("Turso: applied %d/%d schema migrations", applied, len(all_migrations))


def create_run_turso(client, run_id: str, trigger: str,
                     commit_sha: Optional[str], branch: Optional[str]) -> int:
    """Insert a run record and return its PK.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5.3
    Used by: main() turso branch
    """
    client.batch([
        _TursoStatement(
            "INSERT OR IGNORE INTO runs (run_id, trigger, commit_sha, branch, started_at, status) "
            "VALUES (?, ?, ?, ?, datetime('now'), 'running')",
            [run_id, trigger, commit_sha, branch],
        ),
    ])
    rs = client.execute("SELECT id FROM runs WHERE run_id=?", [run_id])
    return rs.rows[0][0]


def finalize_run_turso(client, run_pk: int, status: str) -> None:
    """Update run status to success/error.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5.3
    """
    client.execute(
        "UPDATE runs SET finished_at = datetime('now'), status = ? WHERE id = ?",
        [status, run_pk],
    )


def _build_dimension_stmts(rec: dict) -> list:
    """Build _TursoStatement list for dimension upserts (device, model, prompt).

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5.2
    Used by: ingest_turso()
    """
    return [
        _TursoStatement(
            "INSERT OR IGNORE INTO devices "
            "(manufacturer, model, product, soc, android_version, sdk_int, cpu_cores, max_heap_mb) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [rec["manufacturer"], rec["device_model"], rec["product"],
             rec["soc"], rec["android_version"], rec["sdk_int"],
             rec["cpu_cores"], rec["max_heap_mb"]],
        ),
        _TursoStatement(
            "INSERT OR IGNORE INTO models (model_name, model_path, backend, engine) "
            "VALUES (?, ?, ?, ?)",
            [rec["model_name"], rec["model_path"], rec["backend"], rec["engine"]],
        ),
        _TursoStatement(
            "INSERT OR IGNORE INTO prompts (prompt_id, category, lang, prompt_text) "
            "VALUES (?, ?, ?, ?)",
            [rec["prompt_id"], rec["category"], rec["lang"], rec["prompt_text"]],
        ),
    ]


def _build_result_insert_stmt(rec: dict, run_pk: Optional[int]):
    """Build a single _TursoStatement for results INSERT.

    Why subqueries: Turso batch executes in a single HTTP round-trip.
    Dimension PKs are resolved via inline subqueries instead of separate SELECT calls,
    eliminating extra network round-trips per record.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5.2
    Used by: ingest_turso()
    """
    return _TursoStatement(
        """
        INSERT OR IGNORE INTO results (
            device_id, model_id, prompt_id, run_id,
            status, latency_ms, init_time_ms, response, error,
            ttft_ms, prefill_time_ms, decode_time_ms,
            input_token_count, output_token_count,
            prefill_tps, decode_tps,
            peak_java_memory_mb, peak_native_memory_mb,
            itl_p50_ms, itl_p95_ms, itl_p99_ms,
            battery_level_start, battery_level_end,
            thermal_start, thermal_end,
            voltage_start_mv, voltage_end_mv,
            current_before_ua, current_after_ua,
            system_pss_mb, profiling_error,
            timestamp
        ) VALUES (
            (SELECT id FROM devices WHERE manufacturer=? AND model=? AND product=?),
            (SELECT id FROM models WHERE model_name=? AND model_path=? AND backend=? AND engine=?),
            (SELECT id FROM prompts WHERE prompt_id=?),
            ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?
        )
        """,
        [
            # device subquery params
            rec["manufacturer"], rec["device_model"], rec["product"],
            # model subquery params
            rec["model_name"], rec["model_path"], rec["backend"], rec["engine"],
            # prompt subquery param
            rec["prompt_id"],
            # run_id
            run_pk,
            # result fields
            rec["status"], rec["latency_ms"], rec["init_time_ms"],
            rec["response"], rec["error"],
            rec["ttft_ms"], rec["prefill_time_ms"], rec["decode_time_ms"],
            rec["input_token_count"], rec["output_token_count"],
            rec["prefill_tps"], rec["decode_tps"],
            rec["peak_java_memory_mb"], rec["peak_native_memory_mb"],
            rec["itl_p50_ms"], rec["itl_p95_ms"], rec["itl_p99_ms"],
            rec["battery_level_start"], rec["battery_level_end"],
            rec["thermal_start"], rec["thermal_end"],
            rec["voltage_start_mv"], rec["voltage_end_mv"],
            rec["current_before_ua"], rec["current_after_ua"],
            rec["system_pss_mb"], rec["profiling_error"],
            rec["timestamp"],
        ],
    )


def ingest_turso(client, run_pk: Optional[int]) -> tuple[int, int, int]:
    """Turso용 Batch INSERT 적재.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5
    Used by: main() (CLI entry point)
    Depends on: parse_result_file(), _build_dimension_stmts(), _build_result_insert_stmt()
    """
    inserted = skipped = errors = 0

    json_files = sorted(RESULTS_DIR.rglob("*.json"))
    if not json_files:
        logger.warning("No JSON files found in %s", RESULTS_DIR)
        return inserted, skipped, errors

    # Phase 1: Parse all files and collect valid records
    records = []
    for path in json_files:
        rec = parse_result_file(path)
        if rec is None:
            if path.name.startswith("profile_"):
                skipped += 1
            else:
                errors += 1
            continue
        records.append(rec)

    if not records:
        return inserted, skipped, errors

    # Phase 2: Dimension upserts — deduplicate before batching
    seen_devices = set()
    seen_models = set()
    seen_prompts = set()
    dim_stmts = []

    for rec in records:
        dev_key = (rec["manufacturer"], rec["device_model"], rec["product"])
        if dev_key not in seen_devices:
            seen_devices.add(dev_key)
            dim_stmts.append(_TursoStatement(
                "INSERT OR IGNORE INTO devices "
                "(manufacturer, model, product, soc, android_version, sdk_int, cpu_cores, max_heap_mb) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [rec["manufacturer"], rec["device_model"], rec["product"],
                 rec["soc"], rec["android_version"], rec["sdk_int"],
                 rec["cpu_cores"], rec["max_heap_mb"]],
            ))

        mod_key = (rec["model_name"], rec["model_path"], rec["backend"], rec["engine"])
        if mod_key not in seen_models:
            seen_models.add(mod_key)
            dim_stmts.append(_TursoStatement(
                "INSERT OR IGNORE INTO models (model_name, model_path, backend, engine) "
                "VALUES (?, ?, ?, ?)",
                [rec["model_name"], rec["model_path"], rec["backend"], rec["engine"]],
            ))

        prm_key = rec["prompt_id"]
        if prm_key not in seen_prompts:
            seen_prompts.add(prm_key)
            dim_stmts.append(_TursoStatement(
                "INSERT OR IGNORE INTO prompts (prompt_id, category, lang, prompt_text) "
                "VALUES (?, ?, ?, ?)",
                [rec["prompt_id"], rec["category"], rec["lang"], rec["prompt_text"]],
            ))

    if dim_stmts:
        # Dimension upserts are few — single batch is fine
        for i in range(0, len(dim_stmts), BATCH_SIZE):
            batch = dim_stmts[i:i + BATCH_SIZE]
            client.batch(batch)
        logger.info("Turso: %d dimension upserts sent (%d devices, %d models, %d prompts)",
                     len(dim_stmts), len(seen_devices), len(seen_models), len(seen_prompts))

    # Phase 3: Results INSERT — batch by BATCH_SIZE
    result_stmts = [_build_result_insert_stmt(rec, run_pk) for rec in records]

    for i in range(0, len(result_stmts), BATCH_SIZE):
        batch = result_stmts[i:i + BATCH_SIZE]
        try:
            results = client.batch(batch)
            batch_inserted = sum(1 for r in results if r.rows_affected > 0)
            batch_skipped = sum(1 for r in results if r.rows_affected == 0)
            inserted += batch_inserted
            skipped += batch_skipped
            logger.info("Turso: batch %d-%d → %d inserted, %d skipped",
                        i, i + len(batch), batch_inserted, batch_skipped)
        except Exception as e:
            logger.error("Turso: batch %d-%d failed: %s", i, i + len(batch), e)
            errors += len(batch)

    return inserted, skipped, errors


def sync_ground_truth_turso(client, config_path: Path) -> int:
    """Phase 4a: ground_truth sync for Turso mode.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5
    """
    prompt_map = _load_config_prompt_map(config_path)
    if not prompt_map:
        return 0

    stmts = []
    for prompt_id, vals in prompt_map.items():
        ground_truth = vals["ground_truth"]
        eval_strategy = vals["eval_strategy"]

        valid_strategies = {"deterministic", "deterministic_with_fallback", "structural", "none"}
        if eval_strategy not in valid_strategies:
            logger.warning("Unknown eval_strategy '%s' for prompt '%s' — falling back to 'none'",
                           eval_strategy, prompt_id)
            eval_strategy = "none"

        stmts.append(_TursoStatement(
            "UPDATE prompts SET ground_truth = ?, eval_strategy = ? WHERE prompt_id = ?",
            [ground_truth, eval_strategy, prompt_id],
        ))

    if stmts:
        results = client.batch(stmts)
        updated = sum(1 for r in results if r.rows_affected > 0)
        logger.info("Turso: ground truth synced — %d prompts updated from %s", updated, config_path)
        return updated
    return 0


def print_summary_turso(client) -> None:
    """Print DB summary stats from Turso.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5
    """
    rs = client.execute("""
        SELECT
            COUNT(*)                                    AS total,
            SUM(CASE WHEN status='success' THEN 1 END) AS success,
            SUM(CASE WHEN status='error'   THEN 1 END) AS errors
        FROM results
    """)
    row = rs.rows[0] if rs.rows else (0, 0, 0)
    total   = row[0] or 0
    success = row[1] or 0
    errs    = row[2] or 0

    run_rs = client.execute("""
        SELECT run_id, trigger, branch, started_at, status
        FROM runs ORDER BY id DESC LIMIT 1
    """)

    print(f"Total results in DB : {total}")
    print(f"  success           : {success}")
    print(f"  error             : {errs}")
    if run_rs.rows:
        r = run_rs.rows[0]
        print(f"Latest run          : {r[0]} ({r[1]}) "
              f"branch={r[2]} started={r[3]} status={r[4]}")

    # Phase 4a: validation summary
    val_rs = client.execute("""
        SELECT
            COUNT(validation_status)                                        AS validated,
            SUM(CASE WHEN validation_status='pass'      THEN 1 ELSE 0 END) AS v_pass,
            SUM(CASE WHEN validation_status='fail'      THEN 1 ELSE 0 END) AS v_fail,
            SUM(CASE WHEN validation_status='warn'      THEN 1 ELSE 0 END) AS v_warn,
            SUM(CASE WHEN validation_status='uncertain' THEN 1 ELSE 0 END) AS v_uncertain,
            SUM(CASE WHEN validation_status='skip'      THEN 1 ELSE 0 END) AS v_skip
        FROM results
    """)
    val_row = val_rs.rows[0] if val_rs.rows else (0, 0, 0, 0, 0, 0)
    validated = val_row[0] or 0
    if validated > 0:
        print(f"Validation          : {validated} validated "
              f"(pass={val_row[1]}, fail={val_row[2]}, warn={val_row[3]}, "
              f"uncertain={val_row[4]}, skip={val_row[5]})")

    # Phase 6: resource profiling summary
    prof_rs = client.execute("""
        SELECT
            COUNT(battery_level_start) AS profiled,
            AVG(thermal_end - thermal_start) AS avg_thermal_delta,
            AVG(voltage_end_mv - voltage_start_mv) AS avg_voltage_delta,
            AVG(system_pss_mb) AS avg_pss,
            COUNT(profiling_error) AS prof_errors
        FROM results
        WHERE battery_level_start IS NOT NULL
    """)
    prof_row = prof_rs.rows[0] if prof_rs.rows else (0, 0, 0, 0, 0)
    profiled = prof_row[0] or 0
    if profiled > 0:
        avg_td = prof_row[1] or 0
        avg_vd = prof_row[2] or 0
        avg_pss = prof_row[3] or 0
        prof_errs = prof_row[4] or 0
        print(f"Resource profiling  : {profiled} profiled "
              f"(avg_thermal_delta={avg_td / 10:+.1f}°C, "
              f"avg_voltage_delta={avg_vd:+.0f}mV, "
              f"avg_pss={avg_pss:.0f}MB, "
              f"errors={prof_errs})")


# ── Summary-only mode (LOCAL — 기존 코드 보존) ────────────────────────────────

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

    # Phase 6: resource profiling summary
    prof_row = con.execute("""
        SELECT
            COUNT(battery_level_start) AS profiled,
            AVG(thermal_end - thermal_start) AS avg_thermal_delta,
            AVG(voltage_end_mv - voltage_start_mv) AS avg_voltage_delta,
            AVG(system_pss_mb) AS avg_pss,
            COUNT(profiling_error) AS prof_errors
        FROM results
        WHERE battery_level_start IS NOT NULL
    """).fetchone()
    profiled = prof_row[0] or 0
    if profiled > 0:
        avg_td = prof_row[1] or 0
        avg_vd = prof_row[2] or 0
        avg_pss = prof_row[3] or 0
        prof_errs = prof_row[4] or 0
        print(f"Resource profiling  : {profiled} profiled "
              f"(avg_thermal_delta={avg_td / 10:+.1f}°C, "
              f"avg_voltage_delta={avg_vd:+.0f}mV, "
              f"avg_pss={avg_pss:.0f}MB, "
              f"errors={prof_errs})")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ingest JSON results into SQLite/Turso DB")
    p.add_argument("--results-dir", default=None)
    p.add_argument("--db-path", default=None)
    p.add_argument("--config-path", default=None,
                   help="Path to test_config.json for ground_truth sync")
    p.add_argument("--run-id", default=None)
    p.add_argument("--trigger", default="manual")
    p.add_argument("--commit-sha", default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--summary-only", action="store_true",
                   help="Print DB stats and exit (no ingest)")
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

    # ── Phase 7: Dual-mode branch ────────────────────────────────────────
    if DB_MODE == "turso":
        client = _get_turso_client()
        init_tables_turso(client)

        if args.summary_only:
            print_summary_turso(client)
            client.close()
            return

        run_pk: Optional[int] = None
        if args.run_id:
            run_pk = create_run_turso(client, args.run_id, args.trigger,
                                      args.commit_sha, args.branch)
            logger.info("Turso: run started  run_id=%s trigger=%s branch=%s commit=%s",
                        args.run_id, args.trigger, args.branch, args.commit_sha)

        try:
            inserted, skipped, errors = ingest_turso(client, run_pk)
        except Exception as e:
            if run_pk is not None:
                finalize_run_turso(client, run_pk, "error")
            client.close()
            logger.fatal("Turso ingest failed: %s", e)
            sys.exit(1)

        gt_updated = sync_ground_truth_turso(client, config_path)

        if run_pk is not None:
            if inserted == 0 and errors == 0 and skipped == 0:
                status = "error"
            elif errors and not inserted:
                status = "error"
            else:
                status = "success"
            finalize_run_turso(client, run_pk, status)
            logger.info("Turso: run finished run_id=%s status=%s", args.run_id, status)

        print(f"\nIngest complete (turso) — inserted: {inserted}, skipped: {skipped}, errors: {errors}")
        if gt_updated:
            print(f"Ground truth synced: {gt_updated} prompts")
        client.close()

    else:
        # ── 기존 로컬 SQLite 경로 (변경 없음) ────────────────────────────
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