import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "./data/llm_tester.db")
DB_MODE = os.getenv("DB_MODE", "local")  # "local" | "turso"

logger = logging.getLogger(__name__)

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

_MIGRATE_RUN_ID = """
ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id);
"""

# ── Local (aiosqlite) helpers ──────────────────────────────────────────────────


async def _migrate_columns(db: aiosqlite.Connection) -> None:
    """Idempotent column migrations for all phases."""
    # Phase 2: run_id on results
    async with db.execute("PRAGMA table_info(results)") as cur:
        result_cols = {row[1] async for row in cur}
    if "run_id" not in result_cols:
        await db.execute(_MIGRATE_RUN_ID)

    # Phase 4a: validation_status, validation_detail on results
    if "validation_status" not in result_cols:
        await db.execute("ALTER TABLE results ADD COLUMN validation_status TEXT")
    if "validation_detail" not in result_cols:
        await db.execute("ALTER TABLE results ADD COLUMN validation_detail TEXT")

    # Phase 4a: ground_truth, eval_strategy on prompts
    async with db.execute("PRAGMA table_info(prompts)") as cur:
        prompt_cols = {row[1] async for row in cur}
    if "ground_truth" not in prompt_cols:
        await db.execute("ALTER TABLE prompts ADD COLUMN ground_truth TEXT")
    if "eval_strategy" not in prompt_cols:
        await db.execute("ALTER TABLE prompts ADD COLUMN eval_strategy TEXT NOT NULL DEFAULT 'none'")

    # Phase 5: engine column on models
    async with db.execute("PRAGMA table_info(models)") as cur:
        model_cols = {row[1] async for row in cur}
    if "engine" not in model_cols:
        await db.execute("ALTER TABLE models ADD COLUMN engine TEXT NOT NULL DEFAULT 'mediapipe'")

    # Phase 6: resource profiling columns on results
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
    for col_name, col_type in phase6_cols.items():
        if col_name not in result_cols:
            await db.execute(f"ALTER TABLE results ADD COLUMN {col_name} {col_type}")

    await db.commit()


async def _init_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(_DDL)
    await _migrate_columns(db)


async def cleanup_zombie_runs(db: aiosqlite.Connection) -> None:
    """24시간 이상 'running' 상태인 run을 'error'로 전환."""
    await db.execute("""
        UPDATE runs
        SET status = 'error', finished_at = datetime('now')
        WHERE status = 'running'
          AND started_at < datetime('now', '-24 hours')
    """)
    await db.commit()


# ── Turso (libsql-client) helpers ─────────────────────────────────────────────


async def _migrate_columns_turso(db: Any) -> None:
    """Idempotent column migrations for Turso.

    Turso does not support the async-context-manager PRAGMA pattern.
    Instead, try each ALTER TABLE and silently ignore duplicate-column errors.
    """
    migrations = [
        # Phase 2
        "ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id)",
        # Phase 4a
        "ALTER TABLE results ADD COLUMN validation_status TEXT",
        "ALTER TABLE results ADD COLUMN validation_detail TEXT",
        "ALTER TABLE prompts ADD COLUMN ground_truth TEXT",
        "ALTER TABLE prompts ADD COLUMN eval_strategy TEXT NOT NULL DEFAULT 'none'",
        # Phase 5
        "ALTER TABLE models ADD COLUMN engine TEXT NOT NULL DEFAULT 'mediapipe'",
        # Phase 6
        "ALTER TABLE results ADD COLUMN battery_level_start INTEGER",
        "ALTER TABLE results ADD COLUMN battery_level_end INTEGER",
        "ALTER TABLE results ADD COLUMN thermal_start INTEGER",
        "ALTER TABLE results ADD COLUMN thermal_end INTEGER",
        "ALTER TABLE results ADD COLUMN voltage_start_mv INTEGER",
        "ALTER TABLE results ADD COLUMN voltage_end_mv INTEGER",
        "ALTER TABLE results ADD COLUMN current_before_ua INTEGER",
        "ALTER TABLE results ADD COLUMN current_after_ua INTEGER",
        "ALTER TABLE results ADD COLUMN system_pss_mb REAL",
        "ALTER TABLE results ADD COLUMN profiling_error TEXT",
    ]
    for sql in migrations:
        try:
            await db.execute(sql)
        except Exception as e:
            # Suppress "duplicate column name" — column already exists
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                logger.warning("Migration skipped (%s): %s", sql.split()[5], e)


async def _init_tables_turso(db: Any) -> None:
    """Create tables on Turso via batch (executescript not supported)."""
    statements = [s.strip() for s in _DDL.split(";") if s.strip()]
    await db.batch(statements)
    await _migrate_columns_turso(db)


async def _cleanup_zombie_runs_turso(db: Any) -> None:
    """Turso version — no commit() needed (auto-committed)."""
    await db.execute("""
        UPDATE runs
        SET status = 'error', finished_at = datetime('now')
        WHERE status = 'running'
          AND started_at < datetime('now', '-24 hours')
    """)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app):
    """Architecture: DEPLOYMENT_ARCHITECTURE.md §4.1"""
    if DB_MODE == "turso":
        import libsql_client  # type: ignore[import]
        db = libsql_client.create_client(
            url=os.getenv("TURSO_URL", ""),
            auth_token=os.getenv("TURSO_AUTH_TOKEN", ""),
        )
        # Turso manages WAL/FK server-side — PRAGMA not needed
        await _init_tables_turso(db)
        await _cleanup_zombie_runs_turso(db)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA busy_timeout=5000")
        await _init_tables(db)
        await cleanup_zombie_runs(db)

    app.state.db = db
    app.state.db_mode = DB_MODE
    yield
    await db.close()
