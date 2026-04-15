"""Thin adapter that unifies aiosqlite and libsql-client query interfaces.

Architecture: DEPLOYMENT_ARCHITECTURE.md §4.2
Used by: loader.py, stats.py, main.py (all DB queries)
Depends on: aiosqlite (local mode), libsql-client (turso mode)
"""

from __future__ import annotations

from typing import Any, Optional


class Row(dict):
    """dict subclass that also supports positional access (row[0]).

    Used by: _row_to_item(), list_devices(), all fetchall/fetchone callers.
    Why: aiosqlite.Row supports both row["key"] and row[0]. Returning a plain
         dict would break existing row[0] access patterns without changing SQL.
    """

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class DbAdapter:
    """Absorbs the interface difference between aiosqlite and libsql-client.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §4.2
    Used by: all loader.py and stats.py public functions, main.py endpoints
    Depends on: aiosqlite (local), libsql-client (turso)
    """

    def __init__(self, db: Any, mode: str) -> None:
        self._db = db
        self._mode = mode

    async def fetchall(self, sql: str, params: tuple = ()) -> list[Row]:
        """Run SELECT → list[Row].  Row supports both row["col"] and row[0]."""
        if self._mode == "turso":
            rs = await self._db.execute(sql, list(params))
            columns = rs.columns
            return [Row(zip(columns, row)) for row in rs.rows]
        else:
            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()
            return [Row(row) for row in rows]

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[Row]:
        """Run SELECT → first Row or None."""
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Run INSERT / UPDATE / DELETE (no result needed)."""
        if self._mode == "turso":
            await self._db.execute(sql, list(params))
        else:
            await self._db.execute(sql, params)
            await self._db.commit()

    async def executescript(self, sql: str) -> None:
        """Run multiple semicolon-separated statements."""
        if self._mode == "turso":
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            await self._db.batch(statements)
        else:
            await self._db.executescript(sql)
