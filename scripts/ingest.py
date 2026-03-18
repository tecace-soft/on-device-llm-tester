"""
scripts/ingest.py — JSON → SQLite ingestion

Usage:
    python scripts/ingest.py
    python scripts/ingest.py --results-dir ./results --db-path ./data/llm_tester.db
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_RESULTS_DIR = "./results"
DEFAULT_DB_PATH = "./data/llm_tester.db"


# ── DDL (sync, matches api/db.py) ────────────────────────────────────────────

DDL = """
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

CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id),
    model_id      INTEGER NOT NULL REFERENCES models(id),
    prompt_id     INTEGER NOT NULL REFERENCES prompts(id),

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
CREATE INDEX IF NOT EXISTS idx_results_timestamp ON results(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_results_filter    ON results(device_id, model_id, status);
"""


# ── Report ────────────────────────────────────────────────────────────────────

@dataclass
class IngestReport:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0
    error_files: list[str] = field(default_factory=list)

    def print(self) -> None:
        total = self.inserted + self.skipped + self.errors
        print("\n─────────────────────────────────────")
        print(f"  Ingest complete  —  {total} files scanned")
        print(f"  ✅ Inserted : {self.inserted}")
        print(f"  ⏭  Skipped  : {self.skipped}")
        print(f"  ❌ Errors   : {self.errors}")
        if self.error_files:
            print("\n  Error files:")
            for f in self.error_files:
                print(f"    • {f}")
        print("─────────────────────────────────────\n")


# ── DB helpers ────────────────────────────────────────────────────────────────

def init_db(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    for stmt in DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            db.execute(stmt)
    db.commit()


def upsert_device(db: sqlite3.Connection, d: dict) -> int:
    db.execute(
        """
        INSERT OR IGNORE INTO devices
            (manufacturer, model, product, soc, android_version, sdk_int, cpu_cores, max_heap_mb)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d.get("manufacturer", ""),
            d.get("model", ""),
            d.get("product", ""),
            d.get("soc", ""),
            d.get("android_version", ""),
            int(d.get("sdk_int", 0) or 0),
            int(d.get("cpu_cores", 0) or 0),
            int(d.get("max_heap_mb", 0) or 0),
        ),
    )
    row = db.execute(
        "SELECT id FROM devices WHERE manufacturer=? AND model=? AND product=?",
        (d.get("manufacturer", ""), d.get("model", ""), d.get("product", "")),
    ).fetchone()
    return row[0]


def upsert_model(db: sqlite3.Connection, data: dict) -> int:
    model_name = data.get("model_name", "")
    model_path = data.get("model_path", "")
    backend = data.get("backend", "")
    db.execute(
        """
        INSERT OR IGNORE INTO models (model_name, model_path, backend)
        VALUES (?, ?, ?)
        """,
        (model_name, model_path, backend),
    )
    row = db.execute(
        "SELECT id FROM models WHERE model_name=? AND model_path=? AND backend=?",
        (model_name, model_path, backend),
    ).fetchone()
    return row[0]


def upsert_prompt(db: sqlite3.Connection, data: dict) -> int:
    prompt_id = data.get("prompt_id", "")
    category = data.get("prompt_category", "")
    lang = data.get("prompt_lang", "en")
    prompt_text = data.get("prompt", "")
    db.execute(
        """
        INSERT OR IGNORE INTO prompts (prompt_id, category, lang, prompt_text)
        VALUES (?, ?, ?, ?)
        """,
        (prompt_id, category, lang, prompt_text),
    )
    row = db.execute(
        "SELECT id FROM prompts WHERE prompt_id=?",
        (prompt_id,),
    ).fetchone()
    return row[0]


def insert_result(
    db: sqlite3.Connection,
    data: dict,
    device_id: int,
    model_id: int,
    prompt_id: int,
) -> bool:
    """Returns True if inserted, False if skipped (UNIQUE conflict)."""
    m = data.get("metrics") or {}

    def _float(val) -> float | None:
        try:
            return float(val) if val not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _int(val) -> int | None:
        try:
            return int(val) if val not in (None, "") else None
        except (TypeError, ValueError):
            return None

    cursor = db.execute(
        """
        INSERT OR IGNORE INTO results (
            device_id, model_id, prompt_id,
            status, latency_ms, init_time_ms,
            response, error,
            ttft_ms, prefill_time_ms, decode_time_ms,
            input_token_count, output_token_count,
            prefill_tps, decode_tps,
            peak_java_memory_mb, peak_native_memory_mb,
            itl_p50_ms, itl_p95_ms, itl_p99_ms,
            timestamp
        ) VALUES (
            ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?
        )
        """,
        (
            device_id, model_id, prompt_id,
            data.get("status", "error"),
            _float(data.get("latency_ms")),
            _float(data.get("init_time_ms")),
            data.get("response", ""),
            data.get("error"),
            _float(m.get("ttft_ms")),
            _float(m.get("prefill_time_ms")),
            _float(m.get("decode_time_ms")),
            _int(m.get("input_token_count")),
            _int(m.get("output_token_count")),
            _float(m.get("prefill_tps")),
            _float(m.get("decode_tps")),
            _float(m.get("peak_java_memory_mb")),
            _float(m.get("peak_native_memory_mb")),
            _float(m.get("itl_p50_ms")),
            _float(m.get("itl_p95_ms")),
            _float(m.get("itl_p99_ms")),
            _int(data.get("timestamp")),
        ),
    )
    return cursor.rowcount > 0


# ── Core ─────────────────────────────────────────────────────────────────────

def ingest_file(db: sqlite3.Connection, file_path: str, report: IngestReport) -> None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Parse error [{file_path}]: {e}")
        report.errors += 1
        report.error_files.append(file_path)
        return

    try:
        device_raw = data.get("device") or {}
        device_id = upsert_device(db, device_raw)
        model_id = upsert_model(db, data)
        prompt_id = upsert_prompt(db, data)
        inserted = insert_result(db, data, device_id, model_id, prompt_id)
        if inserted:
            report.inserted += 1
        else:
            report.skipped += 1
    except Exception as e:
        logger.warning(f"DB error [{file_path}]: {e}")
        report.errors += 1
        report.error_files.append(file_path)


def ingest(results_dir: str, db_path: str) -> IngestReport:
    results_path = Path(results_dir)
    if not results_path.is_dir():
        logger.error(f"Results directory not found: {results_dir}")
        return IngestReport()

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    init_db(db)

    report = IngestReport()

    json_files: list[str] = []
    for device_dir in sorted(results_path.iterdir()):
        if not device_dir.is_dir() or device_dir.name.startswith("_"):
            continue
        for model_dir in sorted(device_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            for json_file in sorted(model_dir.glob("*.json")):
                json_files.append(str(json_file))

    logger.info(f"Found {len(json_files)} JSON files in {results_dir}")

    for file_path in json_files:
        ingest_file(db, file_path, report)

    db.commit()
    db.close()
    return report


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest JSON results into SQLite DB")
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--db-path", default=os.getenv("DB_PATH", DEFAULT_DB_PATH))
    args = parser.parse_args()

    logger.info(f"Results dir : {args.results_dir}")
    logger.info(f"DB path     : {args.db_path}")

    report = ingest(args.results_dir, args.db_path)
    report.print()


if __name__ == "__main__":
    main()