#!/usr/bin/env python3

"""
The resource registry, and the two operations every resource page performs.

`register()` is called by each provider module at import; `all()` and
`get()` are what gui/backend/app.py serves. The two verbs are:

    sync(resource, scope, include_deps)  live system -> SQLite cache
    run_action(resource, scope, action, keys, params)  act on chosen rows

Both take progress/cancelled callbacks so gui/backend/jobs.py can stream
them to the browser, and both are ordinary blocking functions: FastAPI runs
them on a worker thread.

Import order matters only in that providers must be imported before the
first all() call, which importing this module guarantees.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Sequence

from gui.backend import connections, db
from gui.backend.resources.types import Action, Context, Dependency, Item, ResourceSpec

_registry: Dict[str, ResourceSpec] = {}


def register(spec: ResourceSpec) -> ResourceSpec:
    """Add a resource to the registry (last registration of an id wins)."""
    if not spec.id or "." not in spec.id:
        raise ValueError(f"resource id must look like 'service.name', got {spec.id!r}")
    if spec.service not in connections.SERVICES:
        raise ValueError(f"{spec.id}: unknown service {spec.service!r}")
    _registry[spec.id] = spec
    return spec


def get(resource_id: str) -> Optional[ResourceSpec]:
    _load_providers()
    return _registry.get(resource_id)


def all() -> List[ResourceSpec]:
    _load_providers()
    return sorted(_registry.values(), key=lambda s: (s.service, s.label))


def by_service() -> Dict[str, List[ResourceSpec]]:
    out: Dict[str, List[ResourceSpec]] = {}
    for spec in all():
        out.setdefault(spec.service, []).append(spec)
    return out


_loaded = False


def _load_providers() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from gui.backend.resources.providers import (  # noqa: F401
        cube, cuc, cucm_cleanup, cucm_config, webex,
    )


# -- sync -----------------------------------------------------------------

_NOOP_PROGRESS: Callable[[int, Optional[int], str], None] = lambda *_a, **_k: None


def sync(resource_id: str, scope: str, include_deps: bool = False,
         params: Optional[Dict[str, str]] = None,
         progress: Callable[[int, Optional[int], str], None] = _NOOP_PROGRESS,
         cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Refetch one resource from one system and replace its cached rows.

    A sync is authoritative: rows the system no longer has are dropped from
    the cache, so the table never shows something that was deleted
    elsewhere. Dependency scanning is a second pass because it costs one or
    more SQL queries per row.
    """
    spec = get(resource_id)
    if spec is None:
        raise KeyError(f"No resource {resource_id!r}")
    if spec.fetch is None:
        raise ValueError(f"{resource_id} cannot be synced (no fetch)")

    started = time.monotonic()
    client = None if spec.service == "CUBE" else connections.get_client(spec.service, scope)
    ctx = Context(service=spec.service, scope=scope, client=client,
                  params=dict(params or {}), progress=progress, cancelled=cancelled)

    progress(0, None, f"Fetching {spec.label} from {scope}...")
    items: List[Item] = list(spec.fetch(ctx) or [])
    progress(len(items), len(items), f"{len(items)} {spec.label.lower()} found")

    if include_deps and spec.deps is not None:
        total = len(items)
        for index, item in enumerate(items, start=1):
            if cancelled():
                progress(index, total, "Cancelled; keeping what was scanned")
                break
            progress(index, total, f"Checking dependencies: {item.key}")
            try:
                found = spec.deps(ctx, item.fields)
                item.deps = list(found or [])
            except Exception as exc:               # one bad row must not lose the sync
                item.deps = None
                progress(index, total, f"{item.key}: dependency check failed ({exc})")

    db.replace_items(resource_id, scope, [i.to_cache() for i in items])
    duration_ms = int((time.monotonic() - started) * 1000)
    db.set_sync_state(resource_id, scope, len(items), duration_ms, "ok")
    return {"resource": resource_id, "scope": scope, "item_count": len(items),
            "duration_ms": duration_ms, "deps_included": bool(include_deps and spec.deps)}


def scan_deps(resource_id: str, scope: str, keys: Sequence[str],
              progress: Callable[[int, Optional[int], str], None] = _NOOP_PROGRESS,
              cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Run the dependency check for chosen rows only, updating the cache."""
    spec = get(resource_id)
    if spec is None or spec.deps is None:
        raise ValueError(f"{resource_id} has no dependency check")
    client = None if spec.service == "CUBE" else connections.get_client(spec.service, scope)
    ctx = Context(service=spec.service, scope=scope, client=client,
                  progress=progress, cancelled=cancelled)
    total, scanned = len(keys), 0
    for index, key in enumerate(keys, start=1):
        if cancelled():
            break
        cached = db.get_item(resource_id, scope, key)
        if cached is None:
            continue
        progress(index, total, f"Checking dependencies: {key}")
        try:
            found: Optional[List[Dependency]] = list(spec.deps(ctx, cached["fields"]) or [])
        except Exception as exc:
            progress(index, total, f"{key}: dependency check failed ({exc})")
            found = None
        db.set_item_deps(resource_id, scope, key,
                         None if found is None else [d.to_dict() for d in found])
        scanned += 1
    return {"resource": resource_id, "scope": scope, "scanned": scanned}


# -- actions --------------------------------------------------------------

def run_action(resource_id: str, scope: str, action_id: str,
               keys: Sequence[str], params: Optional[Dict[str, str]] = None,
               progress: Callable[[int, Optional[int], str], None] = _NOOP_PROGRESS,
               cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Run one action over the chosen rows (or once, for a form action).

    Per-row failures are collected and reported; they do not stop the rest.
    A handler that raises does stop the run, because that means the
    connection itself is gone.
    """
    spec = get(resource_id)
    if spec is None:
        raise KeyError(f"No resource {resource_id!r}")
    action: Optional[Action] = spec.action(action_id)
    if action is None:
        raise KeyError(f"{resource_id} has no action {action_id!r}")

    missing = [f.label for f in action.fields
               if f.required and not str((params or {}).get(f.name, "")).strip()]
    if missing:
        raise ValueError("Required: " + ", ".join(missing))

    client = None if spec.service == "CUBE" else connections.get_client(spec.service, scope)
    ctx = Context(service=spec.service, scope=scope, client=client,
                  params=dict(params or {}), progress=progress, cancelled=cancelled)

    results: List[dict] = []
    removed: List[str] = []

    if action.scope_mode != "selection":
        progress(0, 1, action.label)
        ok, message = _call_handler(action, ctx, None)
        results.append({"key": "", "success": ok, "message": message})
        db.log_action(resource_id, scope, action_id, "", ok, message)
        progress(1, 1, message or action.label)
    else:
        protected = set(spec.protected_keys() or ())
        total = len(keys)
        for index, key in enumerate(keys, start=1):
            if cancelled():
                results.append({"key": key, "success": False, "message": "Cancelled"})
                continue
            cached = db.get_item(resource_id, scope, key)
            if cached is None:
                results.append({"key": key, "success": False,
                                "message": "Not in the local cache; sync first"})
                continue
            if key in protected:
                results.append({"key": key, "success": False,
                                "message": "Protected system object; not changed"})
                continue
            if action.block_when_deps and (cached.get("deps_count") or 0) > 0:
                results.append({"key": key, "success": False,
                                "message": f"In use by {cached['deps_count']} object(s); not changed"})
                continue
            progress(index, total, f"{action.label}: {key}")
            ok, message = _call_handler(action, ctx, cached)
            results.append({"key": key, "success": ok, "message": message})
            db.log_action(resource_id, scope, action_id, key, ok, message)
            if ok and action.removes_row:
                removed.append(key)

    if removed:
        db.delete_items(resource_id, scope, removed)

    succeeded = sum(1 for r in results if r["success"])
    return {"resource": resource_id, "scope": scope, "action": action_id,
            "succeeded": succeeded, "failed": len(results) - succeeded,
            "removed": removed, "results": results,
            "resync": bool(action.resync_after and not action.removes_row)}


def _call_handler(action: Action, ctx: Context, item: Optional[dict]):
    """Normalise a handler's return value to (bool, str)."""
    outcome = action.handler(ctx, item)
    if isinstance(outcome, tuple):
        ok, message = (list(outcome) + [""])[:2]
        return bool(ok), str(message or "")
    if isinstance(outcome, dict):
        return bool(outcome.get("success")), str(outcome.get("message")
                                                 or outcome.get("error") or "")
    return bool(outcome), ""
