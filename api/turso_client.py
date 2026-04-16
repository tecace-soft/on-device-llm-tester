"""Minimal Turso HTTP v2 pipeline client using aiohttp.

Replaces the deprecated libsql-client (WebSocket) library, which caused
HTTP 505 errors on Render. Issues a single HTTP POST per pipeline call
against ``{db_url}/v2/pipeline`` using Bearer token auth.

Architecture: DEPLOYMENT_ARCHITECTURE.md §4.1
Used by: api/db.py (lifespan)
Depends on: aiohttp>=3.9.0

Interface contract (must stay compatible with libsql_client.Client):
  - ``execute(sql, args=None) -> ResultSet``
  - ``batch(statements) -> list[ResultSet]`` (statements: list[str] or list[tuple])
  - ``close() -> None``
  - ResultSet exposes ``.columns`` (list[str]) and ``.rows`` (list[list[Any]]).

This file is additive — db_adapter.py requires NO changes because the
ResultSet shape matches what libsql_client previously returned.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Union

import aiohttp


# ── Type helpers ──────────────────────────────────────────────────────────────


@dataclass
class ResultSet:
    """Mirrors libsql_client.ResultSet for drop-in compatibility."""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    affected_row_count: int = 0
    last_insert_rowid: Optional[int] = None


Statement = Union[str, tuple, list]


# ── Value encoding (Python → Turso pipeline JSON) ─────────────────────────────


def _encode_arg(value: Any) -> dict:
    """Encode a Python value as a Turso pipeline argument.

    Why: Turso's HTTP v2 requires typed argument objects, e.g.
         ``{"type": "integer", "value": "42"}``. Integers/bigints are
         sent as *strings* to avoid JSON float precision loss.
    """
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        # bool must come before int (bool is subclass of int in Python)
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {
            "type": "blob",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    return {"type": "text", "value": str(value)}


def _decode_value(cell: dict) -> Any:
    """Decode a single Turso pipeline cell back to a Python value."""
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "text":
        return cell.get("value", "")
    if t == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


def _normalize_url(url: str) -> str:
    """Convert ``libsql://host`` → ``https://host`` for the HTTP API.

    Why: TURSO_URL values are usually stored in the ``libsql://`` form
         (matching the deprecated WebSocket SDK). The HTTP v2 pipeline
         endpoint requires plain HTTPS.
    """
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    return url


# ── Client ────────────────────────────────────────────────────────────────────


class TursoClient:
    """Async Turso client over HTTP v2 pipeline.

    Used by: api/db.py lifespan() when DB_MODE == "turso".
    Depends on: aiohttp. One shared ClientSession per client instance.
    """

    def __init__(self, url: str, auth_token: str) -> None:
        self._base_url = _normalize_url(url).rstrip("/")
        self._pipeline_url = f"{self._base_url}/v2/pipeline"
        self._auth_token = auth_token
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._auth_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    @staticmethod
    def _normalize_statement(stmt: Statement) -> tuple[str, list[Any]]:
        """Accept either a bare SQL string or a (sql, args) pair."""
        if isinstance(stmt, str):
            return stmt, []
        if isinstance(stmt, (tuple, list)) and len(stmt) == 2:
            sql, args = stmt
            if not isinstance(sql, str):
                raise TypeError(f"Statement SQL must be str, got {type(sql)!r}")
            return sql, list(args) if args else []
        raise TypeError(f"Unsupported statement type: {type(stmt)!r}")

    async def _pipeline(self, stmts: Sequence[tuple[str, list[Any]]]) -> list[ResultSet]:
        """Send a batch of execute requests + close as one HTTP pipeline call."""
        requests: list[dict] = []
        for sql, args in stmts:
            requests.append({
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [_encode_arg(a) for a in args],
                },
            })
        requests.append({"type": "close"})

        session = await self._ensure_session()
        async with session.post(
            self._pipeline_url,
            json={"requests": requests},
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"Turso pipeline HTTP {resp.status}: {text}"
                )
            data = await resp.json()

        results: list[ResultSet] = []
        for entry in data.get("results", []):
            entry_type = entry.get("type")
            if entry_type == "error":
                err = entry.get("error", {})
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"Turso pipeline error: {msg}")
            if entry_type != "ok":
                # "skipped" entries (after an earlier error) — no response
                continue
            resp_body = entry.get("response", {})
            if resp_body.get("type") != "execute":
                # close response → no result
                continue
            result = resp_body.get("result", {}) or {}
            columns = [c.get("name", "") for c in result.get("cols", []) or []]
            rows = [
                [_decode_value(cell) for cell in row]
                for row in (result.get("rows", []) or [])
            ]
            affected = int(result.get("affected_row_count", 0) or 0)
            last_rowid_raw = result.get("last_insert_rowid")
            last_rowid = int(last_rowid_raw) if last_rowid_raw is not None else None
            results.append(
                ResultSet(
                    columns=columns,
                    rows=rows,
                    affected_row_count=affected,
                    last_insert_rowid=last_rowid,
                )
            )
        return results

    # ── Public API ────────────────────────────────────────────────────────

    async def execute(
        self,
        sql: str,
        args: Optional[Sequence[Any]] = None,
    ) -> ResultSet:
        """Run a single SQL statement and return its ResultSet."""
        rs_list = await self._pipeline([(sql, list(args) if args else [])])
        return rs_list[0] if rs_list else ResultSet()

    async def batch(self, statements: Sequence[Statement]) -> list[ResultSet]:
        """Run multiple statements in one HTTP pipeline call.

        Accepts either bare SQL strings (no args) or (sql, args) tuples —
        matches both ``db.py``'s DDL batching and db_adapter's executescript.
        """
        normalized = [self._normalize_statement(s) for s in statements]
        return await self._pipeline(normalized)

    async def close(self) -> None:
        """Close the underlying aiohttp session. Safe to call repeatedly."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
