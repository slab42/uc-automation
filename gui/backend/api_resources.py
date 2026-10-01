#!/usr/bin/env python3

"""
HTTP + WebSocket API for the rich resource pages, the job monitor, the
connection unlock flow and the local database.

Kept out of gui/backend/app.py so that file stays what it was: the script
inventory, the script runner socket, credentials and the static frontend.
create_app() includes this router before the SPA catch-all.

Shape of the whole thing:

    GET  /api/resources                       the catalog, with cache counts
    GET  /api/resources/{id}                  one spec + its targets + sync state
    GET  /api/resources/{id}/items            cached rows (never a live call)
    GET  /api/resources/{id}/export.csv       those rows as a CSV download
    GET  /api/resources/{id}/options          distinct values, for select fields
    POST /api/resources/{id}/sync             live system -> cache, as a job
    POST /api/resources/{id}/deps             dependency scan of chosen rows
    POST /api/resources/{id}/actions/{aid}    run an action, as a job
    GET  /api/jobs, /api/jobs/{id}            progress and result
    POST /api/jobs/{id}/cancel
    WS   /ws/jobs/{id}                        progress stream
    GET  /api/connections                     targets + credential readiness
    POST /api/connections/{svc}/{name}/unlock supply a password for this process
    POST /api/connections/forget              drop held secrets
    GET  /api/db, POST /api/db/sync-all, DELETE /api/db, GET /api/db/actions

Two rules run through all of it:

* A GET never touches a UC system. Pages read the SQLite cache, so they
  open instantly and work with the cluster unreachable; only an explicit
  Sync goes out to the network.
* Anything that can take more than a moment returns a job id instead of
  blocking the request, because a dependency scan is several SQL queries
  per row.

Secrets: unlock takes a password and holds it in memory for this process
only (see connections.py). No endpoint here ever returns one, and job logs
carry provider messages, which the providers are forbidden from putting
secrets into.
"""

from __future__ import annotations

import asyncio
import csv
import io
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from gui.backend import connections, db, jobs, pages
from gui.backend.resources import registry

router = APIRouter()


# -- request bodies -------------------------------------------------------

class SyncRequest(BaseModel):
    #: empty means "every target whose credentials are ready"
    scopes: List[str] = Field(default_factory=list)
    include_deps: bool = False
    params: Dict[str, str] = Field(default_factory=dict)


class DepsRequest(BaseModel):
    scope: str
    keys: List[str] = Field(default_factory=list)


class ActionRequest(BaseModel):
    scope: str
    keys: List[str] = Field(default_factory=list)
    params: Dict[str, str] = Field(default_factory=dict)


class UnlockRequest(BaseModel):
    secret: str
    username: str = ""


class ForgetRequest(BaseModel):
    service: Optional[str] = None
    name: Optional[str] = None


class SyncAllRequest(BaseModel):
    include_deps: bool = False
    #: empty means every resource that has at least one ready target
    resources: List[str] = Field(default_factory=list)


# -- helpers --------------------------------------------------------------

def _spec_or_404(resource_id: str):
    spec = registry.get(resource_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No resource {resource_id}")
    return spec


def _ready_scopes(service: str) -> List[str]:
    return [t["name"] for t in connections.targets_view(service) if t["ready"]]


def _resource_view(spec, counts: Optional[Dict[str, int]] = None) -> dict:
    counts = counts if counts is not None else db.counts_by_resource()
    state = db.get_sync_state(spec.id)
    return {
        **spec.to_dict(),
        "cached_items": counts.get(spec.id, 0),
        "sync_state": state,
        "last_sync": max((s["synced_at"] for s in state), default=None),
    }


def _needs_credentials(exc: connections.NeedsCredentials) -> HTTPException:
    """409 carries enough for the page to draw its unlock form."""
    return HTTPException(status_code=409, detail={
        "code": "needs_credentials",
        "service": exc.service,
        "name": exc.name,
        "username": exc.username,
        "message": f"{exc.service} {exc.name}: {exc.reason}. Unlock it to continue.",
    })


# -- catalog --------------------------------------------------------------

@router.get("/api/resources")
def list_resources() -> dict:
    counts = db.counts_by_resource()
    grouped: Dict[str, List[dict]] = {}
    for spec in registry.all():
        grouped.setdefault(spec.service, []).append(_resource_view(spec, counts))
    return {
        "services": [
            {"service": service,
             "targets": connections.targets_view(service),
             "resources": specs}
            for service, specs in grouped.items()
        ],
    }


@router.get("/api/resources/{resource_id}")
def get_resource(resource_id: str) -> dict:
    spec = _spec_or_404(resource_id)
    return {**_resource_view(spec),
            "targets": connections.targets_view(spec.service)}


@router.get("/api/resources/{resource_id}/items")
def get_items(resource_id: str,
              scope: Optional[str] = Query(default=None),
              scopes: Optional[str] = Query(default=None,
                                            description="comma separated")) -> dict:
    """Cached rows. Never contacts the UC system, so it is always fast."""
    spec = _spec_or_404(resource_id)
    wanted = [s for s in (scopes.split(",") if scopes else [scope] if scope else []) if s]
    items = db.get_items(resource_id, wanted or None)
    return {
        "resource": resource_id,
        "scopes": wanted,
        "columns": [c.to_dict() for c in spec.columns],
        "key_label": spec.key_label,
        "protected_keys": list(spec.protected_keys() or ()),
        "items": items,
        "sync_state": db.get_sync_state(resource_id),
    }


@router.get("/api/resources/{resource_id}/export.csv")
def export_items(resource_id: str,
                 scope: Optional[str] = Query(default=None)) -> Response:
    """The cached rows as a CSV, column order following the spec."""
    spec = _spec_or_404(resource_id)
    items = db.get_items(resource_id, [scope] if scope else None)
    buf = io.StringIO()
    headers = ["scope", "key"] + [c.key for c in spec.columns if c.kind != "deps"]
    if spec.has_deps:
        headers += ["dependency_count", "dependencies"]
    writer = csv.writer(buf)
    writer.writerow(headers)
    for item in items:
        row = [item["scope"], item["key"]]
        row += [item["fields"].get(c.key, "") for c in spec.columns if c.kind != "deps"]
        if spec.has_deps:
            deps = item.get("deps")
            row += ["" if item.get("deps_count") is None else item["deps_count"],
                    "; ".join(f"{d.get('name')} ({d.get('type')})" for d in (deps or []))]
        writer.writerow(row)
    name = f"{resource_id.replace('.', '-')}{'-' + scope if scope else ''}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/resources/{resource_id}/options")
def get_options(resource_id: str, field: str = Query(default="key"),
                scope: Optional[str] = Query(default=None)) -> dict:
    """Distinct values from cached rows, for a select field's option list.

    `field` names a key in Item.fields; a row that has no such key falls
    back to its item key, which is what makes options_from="<res>:name"
    work for the many resources whose name IS the key.
    """
    _spec_or_404(resource_id)
    values = []
    for item in db.get_items(resource_id, [scope] if scope else None):
        value = item["fields"].get(field) if field != "key" else item["key"]
        if value in (None, ""):
            value = item["key"]
        text = str(value)
        if text and text not in values:
            values.append(text)
    return {"resource": resource_id, "field": field, "options": sorted(values)}


# -- sync and actions -----------------------------------------------------

@router.post("/api/resources/{resource_id}/sync")
def sync_resource(resource_id: str, body: SyncRequest) -> dict:
    """Start a sync job for one resource across one or more targets."""
    spec = _spec_or_404(resource_id)
    scopes = body.scopes or _ready_scopes(spec.service)
    if not scopes:
        targets = connections.targets_view(spec.service)
        if not targets:
            raise HTTPException(status_code=400, detail=(
                f"No {spec.service} targets are defined. Add them to "
                f"_DATA/clusters.csv, _DATA/routers.csv or .env/credentials.env."))
        raise HTTPException(status_code=409, detail={
            "code": "needs_credentials",
            "service": spec.service,
            "name": targets[0]["name"],
            "username": targets[0].get("username", ""),
            "message": f"No {spec.service} target has a usable password yet. "
                       f"Unlock one to sync.",
        })

    label = f"Sync {spec.label} ({', '.join(scopes)})"

    def work(job: jobs.Job) -> dict:
        outcomes = []
        for scope in scopes:
            if job.cancelled():
                break
            job.progress(-1, None, f"--- {scope} ---")
            try:
                outcomes.append(registry.sync(
                    resource_id, scope, include_deps=body.include_deps,
                    params=body.params, progress=job.progress,
                    cancelled=job.cancelled))
            except connections.NeedsCredentials as exc:
                message = f"{scope}: {exc.reason}"
                job.progress(-1, None, message)
                db.set_sync_state(resource_id, scope, 0, None, "error", message)
                outcomes.append({"scope": scope, "error": message,
                                 "needs_credentials": True})
            except Exception as exc:
                message = f"{scope}: {type(exc).__name__}: {exc}"
                job.progress(-1, None, message)
                db.set_sync_state(resource_id, scope, 0, None, "error", message)
                outcomes.append({"scope": scope, "error": message})
        return {"resource": resource_id, "scopes": scopes, "outcomes": outcomes}

    job = jobs.start("sync", label, work,
                     meta={"resource": resource_id, "scopes": scopes,
                           "include_deps": body.include_deps})
    return {"job_id": job.id, "label": label}


@router.post("/api/resources/{resource_id}/deps")
def scan_deps(resource_id: str, body: DepsRequest) -> dict:
    """Dependency scan for chosen rows, without refetching the whole list."""
    spec = _spec_or_404(resource_id)
    if not spec.has_deps:
        raise HTTPException(status_code=400,
                            detail=f"{spec.label} has no dependency check")
    if not body.keys:
        raise HTTPException(status_code=400, detail="Select at least one row")
    label = f"Check dependencies: {len(body.keys)} {spec.label.lower()}"

    def work(job: jobs.Job) -> dict:
        try:
            return registry.scan_deps(resource_id, body.scope, body.keys,
                                      progress=job.progress,
                                      cancelled=job.cancelled)
        except connections.NeedsCredentials as exc:
            raise RuntimeError(f"{exc.service} {exc.name}: {exc.reason}") from exc

    job = jobs.start("deps", label, work,
                     meta={"resource": resource_id, "scope": body.scope})
    return {"job_id": job.id, "label": label}


@router.post("/api/resources/{resource_id}/actions/{action_id}")
def run_action(resource_id: str, action_id: str, body: ActionRequest) -> dict:
    """Run an action over the chosen rows (or once, for a form action)."""
    spec = _spec_or_404(resource_id)
    action = spec.action(action_id)
    if action is None:
        raise HTTPException(status_code=404,
                            detail=f"{spec.label} has no action {action_id}")
    if action.scope_mode == "selection" and not body.keys:
        raise HTTPException(status_code=400, detail="Select at least one row")
    if not body.scope:
        raise HTTPException(status_code=400, detail="Choose a target first")

    count = len(body.keys) if action.scope_mode == "selection" else 1
    label = f"{action.label}: {count} {spec.label.lower()}"

    def work(job: jobs.Job) -> dict:
        try:
            outcome = registry.run_action(
                resource_id, body.scope, action_id, body.keys, body.params,
                progress=job.progress, cancelled=job.cancelled)
        except connections.NeedsCredentials as exc:
            raise RuntimeError(f"{exc.service} {exc.name}: {exc.reason}") from exc
        if outcome.get("resync") and not job.cancelled():
            job.progress(-1, None, "Refreshing the cached list...")
            try:
                registry.sync(resource_id, body.scope, include_deps=False,
                              progress=job.progress, cancelled=job.cancelled)
            except Exception as exc:
                job.progress(-1, None, f"Refresh failed: {exc}")
        return outcome

    job = jobs.start("action", label, work,
                     meta={"resource": resource_id, "scope": body.scope,
                           "action": action_id, "count": count})
    return {"job_id": job.id, "label": label}


# -- jobs -----------------------------------------------------------------

@router.get("/api/jobs")
def list_jobs(limit: int = Query(default=20, ge=1, le=60)) -> dict:
    return {"jobs": jobs.recent(limit)}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, log_from: int = Query(default=0, ge=0)) -> dict:
    """Poll a job. `log_from` is the number of log lines already seen."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id}")
    return job.to_dict(log_from=log_from)


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id}")
    job.cancel()
    return job.to_dict(log_from=job.to_dict()["log_total"])


@router.websocket("/ws/jobs/{job_id}")
async def watch_job(ws: WebSocket, job_id: str) -> None:
    """Stream a job's progress. Polls the job object; it lives on a thread."""
    await ws.accept()
    job = jobs.get(job_id)
    if job is None:
        await ws.send_json({"type": "error", "message": f"No job {job_id}"})
        await ws.close()
        return
    sent_lines, last_version = 0, -1
    try:
        while True:
            snapshot = job.to_dict(log_from=sent_lines)
            if snapshot["version"] != last_version:
                last_version = snapshot["version"]
                sent_lines = snapshot["log_total"]
                await ws.send_json({"type": "job", **snapshot})
            if snapshot["status"] != "running":
                break
            await asyncio.sleep(0.25)
        await ws.close()
    except WebSocketDisconnect:
        pass


# -- connections ----------------------------------------------------------

@router.get("/api/connections")
def list_connections() -> dict:
    """Targets per service with credential readiness (never a secret)."""
    return {"services": [{"service": service,
                          "targets": connections.targets_view(service)}
                         for service in connections.SERVICES],
            "wsdl_versions": connections.available_wsdl_versions()}


@router.post("/api/connections/{service}/{name}/unlock")
def unlock_connection(service: str, name: str, body: UnlockRequest) -> dict:
    """Hold a password/token for this target in memory for this process.

    Nothing is written to disk: a password saved permanently belongs in
    .env/credentials.env through the Settings page, which the repo's rules
    already cover. The value is never echoed back.
    """
    service = service.upper()
    if service not in connections.SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service {service}")
    if connections.find_target(service, name) is None and service != "WEBEX":
        raise HTTPException(status_code=404, detail=f"No {service} target {name}")
    if not body.secret:
        raise HTTPException(status_code=400, detail="A password is required")
    try:
        connections.unlock(service, name, body.secret, body.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return connections.credential_status(service, name)


@router.post("/api/connections/forget")
def forget_connections(body: ForgetRequest) -> dict:
    """Drop held secrets and cached clients (a logout for this process)."""
    dropped = connections.forget(body.service, body.name)
    return {"forgotten": dropped}


# -- database -------------------------------------------------------------

@router.get("/api/db")
def db_overview() -> dict:
    """Everything the Database page shows."""
    counts = db.counts_by_resource()
    specs = {s.id: s for s in registry.all()}
    return {
        "stats": db.stats(),
        "resources": [
            {"id": spec.id, "service": spec.service, "label": spec.label,
             "cached_items": counts.get(spec.id, 0),
             "has_deps": spec.has_deps,
             "sync_state": db.get_sync_state(spec.id)}
            for spec in registry.all()
        ],
        "orphan_resources": sorted(set(counts) - set(specs)),
    }


@router.get("/api/db/actions")
def db_actions(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """The action log: what was changed on a UC system from this GUI."""
    return {"actions": db.recent_actions(limit)}


@router.post("/api/db/sync-all")
def sync_all(body: SyncAllRequest) -> dict:
    """One job that resyncs every resource that has a ready target.

    This is the "Sync DB" button: it is the same per-resource sync run in
    sequence, so a failure on one cluster is reported and the rest carry on.
    """
    wanted = [registry.get(r) for r in body.resources] if body.resources else registry.all()
    plan = []
    for spec in wanted:
        if spec is None or spec.fetch is None:
            continue
        for scope in _ready_scopes(spec.service):
            plan.append((spec.id, spec.label, scope))
    if not plan:
        raise HTTPException(status_code=409, detail={
            "code": "needs_credentials",
            "message": "No target has a usable password yet. Unlock a cluster, "
                       "router or Webex org first, or fill in .env/credentials.env.",
        })

    label = f"Sync database: {len(plan)} resource/target pairs"

    def work(job: jobs.Job) -> dict:
        outcomes = []
        for index, (resource_id, res_label, scope) in enumerate(plan, start=1):
            if job.cancelled():
                break
            job.progress(index - 1, len(plan), f"[{index}/{len(plan)}] {res_label} on {scope}")
            try:
                outcomes.append(registry.sync(
                    resource_id, scope, include_deps=body.include_deps,
                    progress=lambda d, t, m: job.progress(-1, None, m),
                    cancelled=job.cancelled))
            except Exception as exc:
                message = f"{res_label} on {scope}: {type(exc).__name__}: {exc}"
                job.progress(-1, None, message)
                db.set_sync_state(resource_id, scope, 0, None, "error", message)
                outcomes.append({"resource": resource_id, "scope": scope,
                                 "error": message})
        job.progress(len(plan), len(plan), "Database sync finished")
        return {"pairs": len(plan), "outcomes": outcomes}

    job = jobs.start("sync_all", label, work, meta={"pairs": len(plan)})
    return {"job_id": job.id, "label": label, "pairs": len(plan)}


@router.delete("/api/db")
def clear_db(resource: Optional[str] = Query(default=None),
             scope: Optional[str] = Query(default=None)) -> dict:
    """Forget cached rows. Always safe: the next sync rebuilds them."""
    removed = db.clear(resource, scope)
    return {"removed": removed, "stats": db.stats()}


# -- page specs -----------------------------------------------------------

@router.get("/api/pages")
def list_pages() -> dict:
    """Which script pages have a rich layout, for the sidebar badge."""
    return {"pages": {rel: spec.to_dict() for rel, spec in pages.PAGES.items()}}
