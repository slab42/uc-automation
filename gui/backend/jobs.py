#!/usr/bin/env python3

"""
Background jobs for the resource pages.

A sync or a bulk action can take a minute (a dependency scan is several SQL
queries per row), which is longer than a browser should wait on one HTTP
request. So the API starts a job, returns its id immediately, and the page
polls GET /api/jobs/{id} - or follows WS /ws/jobs/{id} - for progress, a
running log and the final result.

Jobs run on plain threads, not in the event loop, because the CUCM / CUC /
Webex clients are blocking. Nothing here touches the script runner in
gui/backend/runner.py: that still owns subprocess script runs, and these two
mechanisms are independent on purpose.

Only the last MAX_JOBS finished jobs are kept, in memory; jobs do not
survive a server restart, and their log never contains a secret because the
providers are given already-resolved clients.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

MAX_JOBS = 60
MAX_LOG_LINES = 4000


class Job:
    """One running or finished unit of work."""

    def __init__(self, kind: str, label: str, meta: Optional[dict] = None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind                      # 'sync' | 'action' | 'deps' | 'sync_all'
        self.label = label
        self.meta = meta or {}
        self.status = "running"               # running | done | error | cancelled
        self.done = 0
        self.total: Optional[int] = None
        self.message = ""
        self.log: List[str] = []
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.finished_at: Optional[str] = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._version = 0                     # bumps on every change, for pollers

    # -- called from the worker thread ------------------------------------

    def progress(self, done: int, total: Optional[int] = None, message: str = "") -> None:
        """Report progress. done < 0 means "log this, the counter is unchanged"."""
        with self._lock:
            if done >= 0:
                self.done = done
            if total is not None:
                self.total = total
            if message:
                self.message = message
                self.log.append(message)
                if len(self.log) > MAX_LOG_LINES:
                    del self.log[: len(self.log) - MAX_LOG_LINES]
            self._version += 1

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- called from the request thread -----------------------------------

    def cancel(self) -> None:
        self._cancel.set()
        self.progress(-1, None, "Stop requested; finishing the current item...")

    def to_dict(self, log_from: int = 0) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "meta": self.meta,
                "status": self.status,
                "done": self.done,
                "total": self.total,
                "message": self.message,
                "log": self.log[log_from:],
                "log_total": len(self.log),
                "result": self.result,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "version": self._version,
            }


_jobs: Dict[str, Job] = {}
_order: List[str] = []
_jobs_lock = threading.Lock()


def start(kind: str, label: str, fn: Callable[[Job], dict],
          meta: Optional[dict] = None) -> Job:
    """Run fn(job) on a worker thread and return the job straight away."""
    job = Job(kind, label, meta)
    with _jobs_lock:
        _jobs[job.id] = job
        _order.append(job.id)
        while len(_order) > MAX_JOBS:
            stale = _order.pop(0)
            if _jobs.get(stale) and _jobs[stale].status == "running":
                _order.append(stale)          # never evict a running job
                break
            _jobs.pop(stale, None)

    def _run() -> None:
        try:
            job.result = fn(job)
            job.status = "cancelled" if job.cancelled() else "done"
        except Exception as exc:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress(-1, None, job.error)
            job.meta = {**job.meta, "traceback": traceback.format_exc(limit=8)}
        finally:
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            job.progress(-1, None, "")

    threading.Thread(target=_run, name=f"ucjob-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Optional[Job]:
    with _jobs_lock:
        return _jobs.get(job_id)


def recent(limit: int = 20) -> List[dict]:
    with _jobs_lock:
        ids = list(reversed(_order))[:limit]
        jobs = [_jobs[i] for i in ids if i in _jobs]
    return [{k: v for k, v in j.to_dict().items() if k != "log"} for j in jobs]
