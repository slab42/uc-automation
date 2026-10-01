#!/usr/bin/env python3

"""
Offline self-check for the resource registry.

Run it from the repo root after adding or editing a provider:

    python3 -m gui.backend.resources.check
    python3 -m gui.backend.resources.check --verbose

It imports every provider, validates the declarations that the frontend
depends on, cross-checks gui/backend/pages.py against the registry, and
prints the catalog. It never connects to a cluster, so it is safe to run
anywhere; exit status is 1 when anything is wrong.
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.backend import connections, pages                                # noqa: E402
from gui.backend.resources import registry                                # noqa: E402
from gui.backend.resources.types import COLUMN_KINDS, FIELD_KINDS         # noqa: E402

VALID_SCOPE_MODES = ("selection", "form", "none")
VALID_STYLES = ("primary", "secondary", "danger")


def check() -> list:
    """Return a list of problem strings (empty means everything is consistent)."""
    problems = []
    specs = registry.all()
    ids = {s.id for s in specs}

    for spec in specs:
        where = spec.id
        if spec.service not in connections.SERVICES:
            problems.append(f"{where}: service {spec.service!r} is not one of {connections.SERVICES}")
        if spec.fetch is None:
            problems.append(f"{where}: no fetch callable")
        elif len(inspect.signature(spec.fetch).parameters) != 1:
            problems.append(f"{where}: fetch must take exactly one argument (ctx)")
        if spec.deps is not None and len(inspect.signature(spec.deps).parameters) != 2:
            problems.append(f"{where}: deps must take two arguments (ctx, fields)")
        if not spec.columns:
            problems.append(f"{where}: no columns declared")

        column_keys = set()
        for col in spec.columns:
            if col.kind not in COLUMN_KINDS:
                problems.append(f"{where}: column {col.key!r} has unknown kind {col.kind!r}")
            if col.key in column_keys:
                problems.append(f"{where}: duplicate column key {col.key!r}")
            column_keys.add(col.key)
            if col.kind == "deps" and not spec.has_deps:
                problems.append(f"{where}: column {col.key!r} is kind 'deps' but the "
                                f"resource has no deps callable")

        action_ids = set()
        for action in spec.actions:
            if action.id in action_ids:
                problems.append(f"{where}: duplicate action id {action.id!r}")
            action_ids.add(action.id)
            if action.scope_mode not in VALID_SCOPE_MODES:
                problems.append(f"{where}.{action.id}: scope_mode {action.scope_mode!r} "
                                f"is not one of {VALID_SCOPE_MODES}")
            if action.style not in VALID_STYLES:
                problems.append(f"{where}.{action.id}: style {action.style!r} "
                                f"is not one of {VALID_STYLES}")
            if action.block_when_deps and not spec.has_deps:
                problems.append(f"{where}.{action.id}: block_when_deps needs a deps callable")
            if not callable(action.handler):
                problems.append(f"{where}.{action.id}: handler is not callable")
            elif len(inspect.signature(action.handler).parameters) != 2:
                problems.append(f"{where}.{action.id}: handler must take two arguments "
                                f"(ctx, item)")
            if action.style == "danger" and not action.confirm:
                problems.append(f"{where}.{action.id}: a danger action needs a confirm message")
            for fld in action.fields:
                if fld.kind not in FIELD_KINDS:
                    problems.append(f"{where}.{action.id}: field {fld.name!r} has unknown "
                                    f"kind {fld.kind!r}")
                if fld.options_from and fld.options_from.split(":")[0] not in ids:
                    problems.append(f"{where}.{action.id}: field {fld.name!r} points at "
                                    f"unknown resource {fld.options_from!r}")

        for fld in spec.filters:
            if fld.kind not in FIELD_KINDS:
                problems.append(f"{where}: filter {fld.name!r} has unknown kind {fld.kind!r}")

    for rel, page in pages.PAGES.items():
        for rid in page.resources:
            if rid not in ids:
                problems.append(f"pages.py {rel}: resource {rid!r} is not registered")
        known_actions = {a.id for rid in page.resources if rid in ids
                         for a in registry.get(rid).actions}
        for hidden in page.hide_actions:
            if hidden not in known_actions:
                problems.append(f"pages.py {rel}: hide_actions has {hidden!r}, which none "
                                f"of its resources declare")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the GUI resource registry")
    parser.add_argument("--verbose", action="store_true",
                        help="list every column and action, not just the resources")
    args = parser.parse_args()

    specs = registry.all()
    service = None
    for spec in specs:
        if spec.service != service:
            service = spec.service
            print(f"\n{service}")
        deps = "deps" if spec.has_deps else "    "
        actions = ",".join(a.id for a in spec.actions) or "-"
        print(f"  {spec.id:<38} {deps}  {len(spec.columns):>2} cols  [{actions}]")
        if args.verbose:
            for col in spec.columns:
                print(f"       col {col.key:<24} {col.kind}")
            for action in spec.actions:
                print(f"       act {action.id:<24} {action.scope_mode}/{action.style}"
                      f"{' block_when_deps' if action.block_when_deps else ''}")

    covered = set(pages.referenced_resource_ids())
    orphans = [s.id for s in specs if s.id not in covered]
    print(f"\n{len(specs)} resources, {len(pages.PAGES)} script pages mapped")
    if orphans:
        print(f"Not on any script page (browsable under Resources): {', '.join(orphans)}")

    problems = check()
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nRegistry OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
