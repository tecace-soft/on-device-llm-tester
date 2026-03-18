import os
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "./data/llm_tester.db")

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


async def _init_db(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
    for stmt in DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            await db.execute(stmt)
    await db.commit()


@asynccontextmanager
async def lifespan(app):
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await _init_db(db)
    app.state.db = db
    yield
    await db.close()


async def fetchall(db: aiosqlite.Connection, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
    async with db.execute(query, params) as cursor:
        return await cursor.fetchall()


async def fetchone(db: aiosqlite.Connection, query: str, params: tuple = ()) -> aiosqlite.Row | None:
    async with db.execute(query, params) as cursor:
        return await cursor.fetchone()


async def execute(db: aiosqlite.Connection, query: str, params: tuple = ()) -> int:
    """Returns lastrowid."""
    async with db.execute(query, params) as cursor:
        await db.commit()
        return cursor.lastrowid