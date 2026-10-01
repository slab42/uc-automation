#!/usr/bin/env python3

"""
The resource contract: what a GUI resource page is made of.

A "resource" is one kind of object on a UC system that the web GUI can list,
cache, inspect and act on: CUCM softkey templates, CUC call handlers, Webex
locations, and so on. Declaring one here is all it takes to get a full page
in the browser - sync button, sortable/filterable table, a dependencies
column, per-row checkboxes with select all / unselect all, and action
buttons - because gui/frontend renders every resource page from this
declaration. There is no per-resource frontend code.

A provider module (gui/backend/resources/providers/*.py) builds a
ResourceSpec and calls register() with it. The registry is imported once by
gui/backend/app.py.

Contracts a provider must honour:

* fetch(ctx) returns a list of Item. Nothing is cached inside a provider;
  the framework writes what fetch returns into the SQLite cache, replacing
  the previous rows for that scope.
* Item.key must be stable and unique within a scope, because it is the
  cache primary key and the handle every action is given.
* Item.fields keys must match the Column.key values of the spec, and hold
  JSON-serialisable scalars (str / int / float / bool / None).
* deps(ctx, item) returns a list of Dependency, or [] for "checked, none
  found". Returning None means "not checked", which the table shows as a
  dash rather than a zero, so never use None to mean zero.
* An action handler returns (success, message). It must not raise for an
  expected failure (the API surfaces the message per row); raising is
  reserved for a broken connection, and aborts the remaining rows.
* Nothing in here may print, prompt or call getpass: this code runs inside
  the web server. Progress goes through ctx.progress().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

# -- table description ----------------------------------------------------

#: Column.kind values the frontend knows how to render.
#:   text    plain string
#:   number  right-aligned, thousands separated
#:   bool    check / dash
#:   badge   pill, coloured by value via Column.tone_map
#:   deps    the dependency count, expandable to the list (needs spec.deps)
#:   list    a JSON array of strings, shown as pills
#:   bytes   human-readable size
#:   date    local date/time
COLUMN_KINDS = ("text", "number", "bool", "badge", "deps", "list", "bytes", "date")


@dataclass
class Column:
    """One column of a resource table."""

    key: str
    label: str
    kind: str = "text"
    width: Optional[str] = None
    #: value -> tone name ('ok', 'warn', 'danger', 'info', 'muted') for badges
    tone_map: Dict[str, str] = field(default_factory=dict)
    #: hide by default behind the column picker
    optional: bool = False
    help: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "width": self.width, "tone_map": self.tone_map,
                "optional": self.optional, "help": self.help}


#: Field.kind values the frontend knows how to render in an action form.
FIELD_KINDS = ("text", "number", "select", "bool", "textarea", "secret", "data_file")


@dataclass
class Field:
    """One input in an action form (or in a resource's fetch filter)."""

    name: str
    label: str
    kind: str = "text"
    default: str = ""
    required: bool = False
    options: Sequence[str] = ()
    placeholder: str = ""
    help: str = ""
    #: for kind='select', pull the options from another resource's rows:
    #: "resource_id:field" e.g. "cucm.route_partitions:name"
    options_from: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "kind": self.kind,
                "default": self.default, "required": self.required,
                "options": list(self.options), "placeholder": self.placeholder,
                "help": self.help, "options_from": self.options_from}


@dataclass
class Action:
    """A button on a resource page.

    scope_mode decides how the button behaves:
      'selection'  enabled once rows are ticked; the handler runs per row
      'form'       always enabled; opens the form, handler runs once
      'none'       always enabled, no form, handler runs once (a report/refresh)
    """

    id: str
    label: str
    handler: Callable
    scope_mode: str = "selection"
    style: str = "secondary"          # primary | secondary | danger
    confirm: str = ""                 # non-empty means confirm before running
    #: refuse rows whose deps_count > 0 (what makes "delete only the unused
    #: ones" safe without the operator having to eyeball the table)
    block_when_deps: bool = False
    #: drop the row from the cache after the handler succeeds
    removes_row: bool = False
    #: re-sync the resource after the action finishes
    resync_after: bool = True
    fields: Sequence[Field] = ()
    help: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "scope_mode": self.scope_mode,
                "style": self.style, "confirm": self.confirm,
                "block_when_deps": self.block_when_deps,
                "removes_row": self.removes_row,
                "fields": [f.to_dict() for f in self.fields], "help": self.help}


# -- data returned by providers -------------------------------------------

@dataclass
class Dependency:
    """One thing that references a resource row and blocks deleting it."""

    name: str
    type: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type, "detail": self.detail}


@dataclass
class Item:
    """One row of a resource."""

    key: str
    fields: Dict[str, object] = field(default_factory=dict)
    #: None = dependencies not checked; [] = checked and none found
    deps: Optional[List[Dependency]] = None

    def to_cache(self) -> dict:
        return {
            "key": self.key,
            "fields": self.fields,
            "deps": None if self.deps is None else [d.to_dict() for d in self.deps],
        }


# -- what a provider is handed --------------------------------------------

@dataclass
class Context:
    """Everything a fetch / deps / handler call gets.

    `client` is the live ucmAPI.AXL, cucAPI.CUC or webexAPI.Webex for
    `scope`; CUBE providers get None and open their own session. `params`
    holds the action form values (or the page's filter values on a fetch).
    """

    service: str
    scope: str
    client: object
    params: Dict[str, str] = field(default_factory=dict)
    #: progress(done, total, message) -> None; safe to call often
    progress: Callable[[int, Optional[int], str], None] = lambda *_a, **_k: None
    #: cancelled() -> True once the user pressed Stop on the job
    cancelled: Callable[[], bool] = lambda: False

    def log(self, message: str) -> None:
        self.progress(-1, None, message)


# -- the resource itself --------------------------------------------------

@dataclass
class ResourceSpec:
    """A listable, cacheable kind of object on a UC system."""

    id: str                       # 'cucm.softkey_templates'
    service: str                  # CUCM | CUC | WEBEX | CUBE
    label: str                    # 'Softkey Templates'
    key_label: str = "Name"       # what the key column is called
    description: str = ""
    columns: Sequence[Column] = ()
    fetch: Optional[Callable[[Context], List[Item]]] = None
    deps: Optional[Callable[[Context, dict], List[Dependency]]] = None
    deps_label: str = "Dependencies"
    #: a dependency scan is usually many SQL queries per row, so the page
    #: asks before including it when this is True
    deps_expensive: bool = True
    actions: Sequence[Action] = ()
    #: filter inputs shown above the table and passed to fetch via ctx.params
    filters: Sequence[Field] = ()
    #: names of rows the system will not let you delete, shown greyed out
    protected_keys: Callable[[], Sequence[str]] = lambda: ()
    sync_note: str = ""
    docs_url: str = ""

    @property
    def has_deps(self) -> bool:
        return self.deps is not None

    def action(self, action_id: str) -> Optional[Action]:
        for a in self.actions:
            if a.id == action_id:
                return a
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service": self.service,
            "label": self.label,
            "key_label": self.key_label,
            "description": self.description,
            "columns": [c.to_dict() for c in self.columns],
            "has_deps": self.has_deps,
            "deps_label": self.deps_label,
            "deps_expensive": self.deps_expensive,
            "actions": [a.to_dict() for a in self.actions],
            "filters": [f.to_dict() for f in self.filters],
            "protected_keys": list(self.protected_keys() or ()),
            "sync_note": self.sync_note,
            "docs_url": self.docs_url,
        }
