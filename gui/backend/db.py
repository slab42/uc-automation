#!/usr/bin/env python3

"""
SQLite cache for the web GUI's resource pages.

Every resource page (softkey templates, route partitions, call handlers,
Webex locations, ...) reads its rows from here instead of hitting CUCM /
CUC / Webex on every page view. A "Sync" button on the page, or "Sync all"
on the Database page, refetches from the live system and replaces the rows
for that (resource, scope) pair.

The schema is deliberately generic: one row per cached object with its
fields as a JSON payload, so adding a resource to
gui/backend/resources/registry.py needs no migration here.

    resource   registry id, e.g. 'cucm.softkey_templates'
    scope      the system the row came from: cluster name, router hostname
               or Webex org identifier
    item_key   natural key inside that scope (usually the object name)

Nothing secret is ever written to this file: payloads hold configuration
objects only, and credentials live in memory (see connections.py) or in
.env/credentials.env.

The database file is _DATA/uc_cache.db and is not checked in. Deleting it is
always safe: the next sync rebuilds it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "_DATA" / "uc_cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_items (
    resource    TEXT NOT NULL,
    scope       TEXT NOT NULL,
    item_key    TEXT NOT NULL,
    payload     TEXT NOT NULL,
    deps        TEXT,
    deps_count  INTEGER,
    synced_at   TEXT NOT NULL,
    PRIMARY KEY (resource, scope, item_key)
);

CREATE INDEX IF NOT EXISTS idx_resource_items_resource
    ON resource_items (resource);

CREATE TABLE IF NOT EXISTS sync_state (
    resource    TEXT NOT NULL,
    scope       TEXT NOT NULL,
    synced_at   TEXT NOT NULL,
    item_count  INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'ok',
    message     TEXT,
    PRIMARY KEY (resource, scope)
);

CREATE TABLE IF NOT EXISTS action_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    resource  TEXT,
    scope     TEXT,
    action    TEXT,
    item_key  TEXT,
    success   INTEGER NOT NULL DEFAULT 1,
    message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_action_log_at ON action_log (at DESC);
"""

_init_lock = threading.Lock()
_initialised = False


def now_iso() -> str:
    """Timestamp used for every synced_at / at column."""
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    """Yield a connection with row factory set, committing on clean exit.

    A connection per call keeps this safe under FastAPI's threadpool, which
    runs the sync endpoints on worker threads.
    """
    _ensure_init()
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_init() -> None:
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _initialised = True


def init() -> Path:
    """Create the database file and schema if missing; return its path."""
    _ensure_init()
    return DB_PATH


# -- items ----------------------------------------------------------------

def _row_to_item(row: sqlite3.Row) -> dict:
    payload = json.loads(row["payload"]) if row["payload"] else {}
    deps = json.loads(row["deps"]) if row["deps"] else None
    return {
        "key": row["item_key"],
        "scope": row["scope"],
        "fields": payload,
        "deps": deps,
        "deps_count": row["deps_count"],
        "synced_at": row["synced_at"],
    }


def replace_items(resource: str, scope: str, items: Sequence[dict]) -> int:
    """Replace every cached row for (resource, scope) with `items`.

    Each item is {'key': str, 'fields': dict, 'deps': list|None}. Rows that
    the live system no longer has therefore disappear, which is what makes a
    sync authoritative rather than additive.
    """
    stamp = now_iso()
    with connect() as conn:
        conn.execute("DELETE FROM resource_items WHERE resource = ? AND scope = ?",
                     (resource, scope))
        conn.executemany(
            "INSERT INTO resource_items"
            " (resource, scope, item_key, payload, deps, deps_count, synced_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    resource,
                    scope,
                    str(item.get("key", "")),
                    json.dumps(item.get("fields") or {}, default=str),
                    json.dumps(item["deps"], default=str) if item.get("deps") is not None else None,
                    len(item["deps"]) if item.get("deps") is not None else None,
                    stamp,
                )
                for item in items
            ],
        )
    return len(items)


def set_item_deps(resource: str, scope: str, item_key: str,
                  deps: Optional[List[dict]]) -> None:
    """Attach (or clear) the dependency list of one cached row."""
    with connect() as conn:
        conn.execute(
            "UPDATE resource_items SET deps = ?, deps_count = ?"
            " WHERE resource = ? AND scope = ? AND item_key = ?",
            (
                json.dumps(deps, default=str) if deps is not None else None,
                len(deps) if deps is not None else None,
                resource, scope, item_key,
            ),
        )


def get_items(resource: str, scopes: Optional[Iterable[str]] = None) -> List[dict]:
    """Cached rows for a resource, optionally limited to given scopes."""
    sql = "SELECT * FROM resource_items WHERE resource = ?"
    params: List[object] = [resource]
    scope_list = [s for s in (scopes or []) if s]
    if scope_list:
        sql += " AND scope IN (%s)" % ",".join("?" * len(scope_list))
        params.extend(scope_list)
    sql += " ORDER BY scope, item_key COLLATE NOCASE"
    with connect() as conn:
        return [_row_to_item(r) for r in conn.execute(sql, params)]


def get_item(resource: str, scope: str, item_key: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM resource_items WHERE resource = ? AND scope = ? AND item_key = ?",
            (resource, scope, item_key),
        ).fetchone()
    return _row_to_item(row) if row else None


def delete_items(resource: str, scope: str, keys: Sequence[str]) -> int:
    """Forget rows locally (used after a successful delete on the system)."""
    if not keys:
        return 0
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM resource_items WHERE resource = ? AND scope = ? AND item_key IN (%s)"
            % ",".join("?" * len(keys)),
            [resource, scope, *keys],
        )
        return cur.rowcount


# -- sync state -----------------------------------------------------------

def set_sync_state(resource: str, scope: str, item_count: int,
                   duration_ms: Optional[int] = None, status: str = "ok",
                   message: Optional[str] = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO sync_state"
            " (resource, scope, synced_at, item_count, duration_ms, status, message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(resource, scope) DO UPDATE SET"
            "   synced_at=excluded.synced_at, item_count=excluded.item_count,"
            "   duration_ms=excluded.duration_ms, status=excluded.status,"
            "   message=excluded.message",
            (resource, scope, now_iso(), item_count, duration_ms, status, message),
        )


def get_sync_state(resource: Optional[str] = None) -> List[dict]:
    sql = "SELECT * FROM sync_state"
    params: List[object] = []
    if resource:
        sql += " WHERE resource = ?"
        params.append(resource)
    sql += " ORDER BY resource, scope"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


# -- action log -----------------------------------------------------------

def log_action(resource: str, scope: str, action: str, item_key: str,
               success: bool, message: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO action_log (at, resource, scope, action, item_key, success, message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now_iso(), resource, scope, action, item_key, 1 if success else 0, message),
        )


def recent_actions(limit: int = 100) -> List[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {**dict(r), "success": bool(r["success"])}
        for r in rows
    ]


# -- housekeeping ---------------------------------------------------------

def counts_by_resource() -> Dict[str, int]:
    with connect() as conn:
        return {
            r["resource"]: r["n"]
            for r in conn.execute(
                "SELECT resource, COUNT(*) AS n FROM resource_items GROUP BY resource")
        }


def clear(resource: Optional[str] = None, scope: Optional[str] = None) -> int:
    """Drop cached rows. No argument clears the whole cache."""
    sql = "DELETE FROM resource_items"
    where, params = [], []
    if resource:
        where.append("resource = ?")
        params.append(resource)
    if scope:
        where.append("scope = ?")
        params.append(scope)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with connect() as conn:
        removed = conn.execute(sql, params).rowcount
        state_sql = "DELETE FROM sync_state"
        if where:
            state_sql += " WHERE " + " AND ".join(where)
        conn.execute(state_sql, params)
    return removed


def stats() -> dict:
    """Summary for the Database page."""
    path = init()
    try:
        shown = str(path.relative_to(ROOT))
    except ValueError:
        shown = str(path)
    with connect() as conn:
        items = conn.execute("SELECT COUNT(*) FROM resource_items").fetchone()[0]
        resources = conn.execute(
            "SELECT COUNT(DISTINCT resource) FROM resource_items").fetchone()[0]
        scopes = conn.execute(
            "SELECT COUNT(DISTINCT scope) FROM resource_items").fetchone()[0]
        last = conn.execute("SELECT MAX(synced_at) FROM sync_state").fetchone()[0]
    return {
        "path": shown,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "item_count": items,
        "resource_count": resources,
        "scope_count": scopes,
        "last_sync": last,
    }
