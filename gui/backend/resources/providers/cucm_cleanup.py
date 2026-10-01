#!/usr/bin/env python3

"""
CUCM cleanup resources: softkey templates, phone button templates, route
partitions, calling search spaces, locations and regions.

These are the six dial-plan/config objects the "remediate_*" and
"clean_unused_*" CLI scripts already know how to list, dependency-check and
delete. This module reproduces that same read-only survey plus delete
behaviour as GUI resources, calling the same cucm/ucmAPI.py AXL methods the
CLI scripts use.

Non-obvious AXL/SQL behaviour worth knowing before touching this file:

* AXL's listX calls only return the tags named in `returnedTags`, so
  list_RoutePartitions()/list_Locations()/list_Regions() rows carry only a
  `name` key (the CLI scripts that inspired this file never asked AXL for
  more). Columns that want a richer field (description, bandwidth, codec
  list) are read defensively with .get(..., '') so a CUCM version that omits
  the field degrades to a blank cell instead of a KeyError.
* The dependency finders (find_*_dependencies) run a battery of SQL SELECTs
  against AXL's read-only DB views and swallow individual table/column
  misses (different CUCM schema versions name things differently), so a
  dependency result of [] can legitimately mean "none of the tried tables
  matched" as well as "truly unused". That is the same ambiguity the CLI
  scripts live with.
* Only softkey templates have a system-object exclusion file in _DATA
  (system_softkey_templates.txt). Route partitions, calling search spaces,
  locations and regions have no such file; the reference CLI scripts
  (remediate_partitions.py, remediate_callingSearchSpaces.py,
  remediate_locations.py, remediate_regions.py) instead hard-code a small
  SYSTEM_* name set for informational filtering. This module keeps those
  same hard-coded sets to drive a "system" column, but per the protected_keys
  contract here, only the file-backed softkey templates set is wired into
  protected_keys (greyed out + delete-blocked); the hard-coded sets are
  informational only, and an operator can still attempt to delete a system
  CSS/location/region (the dependency check remains the real safety net).
* Phone button template rows carry `isUserModifiable`; a template with this
  false is the built-in ones and cannot be deleted, so it drives that
  resource's own "system" column the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from gui.backend.resources.registry import register
from gui.backend.resources.types import Action, Column, Context, Dependency, Item, ResourceSpec

ROOT = Path(__file__).resolve().parents[4]

# -- system-object lists ---------------------------------------------------

_SOFTKEY_SYSTEM_FILE = ROOT / "_DATA" / "system_softkey_templates.txt"
_softkey_system_cache: Sequence[str] = None  # type: ignore[assignment]

# Hard-coded, informational only (see module docstring); mirrors the
# reference CLI scripts' SYSTEM_* constants.
_SYSTEM_CSS = {"Default", "Default_Intra_CompanyCS", "Default_CUBE"}
_SYSTEM_LOCATIONS = {"Phantom", "Shadow", "Hub_None"}
_SYSTEM_REGIONS = {"Default"}


def _softkey_protected_keys() -> Sequence[str]:
    """Names from _DATA/system_softkey_templates.txt, cached after first read."""
    global _softkey_system_cache
    if _softkey_system_cache is not None:
        return _softkey_system_cache
    names: List[str] = []
    try:
        if _SOFTKEY_SYSTEM_FILE.is_file():
            for line in _SOFTKEY_SYSTEM_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    names.append(line)
    except OSError:
        names = []
    _softkey_system_cache = tuple(names)
    return _softkey_system_cache


def _deps_from_rows(rows) -> List[Dependency]:
    """find_*_dependencies() rows are {'name': ..., 'type': ...} dicts."""
    out: List[Dependency] = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        if not name:
            continue
        out.append(Dependency(name=name, type=str(row.get("type") or "")))
    return out


# -- softkey templates ------------------------------------------------------

def _fetch_softkey_templates(ctx: Context) -> List[Item]:
    result = ctx.client.list_softkey_templates()
    rows = result.get("response") or []
    system_names = set(_softkey_protected_keys())
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        ctx.progress(index, total, f"Softkey template: {name}")
        items.append(Item(key=name, fields={
            "description": row.get("description") or "",
            "system": name in system_names,
        }))
    return items


def _deps_softkey_template(ctx: Context, fields: dict) -> List[Dependency]:
    # deps(ctx, fields) only ever gets Item.fields, which does not carry the
    # key on its own, so _with_name_field() below copies it into fields['name'].
    name = fields.get("name")
    result = ctx.client.find_softkey_template_dependencies(name)
    return _deps_from_rows(result.get("response"))


def _delete_softkey_template(ctx: Context, item: dict):
    name = item["key"]
    result = ctx.client.delete_softkey_template(name)
    if result.get("success"):
        return True, result.get("response") or "Deleted"
    return False, result.get("error") or "Delete failed"


# -- phone button templates -------------------------------------------------

def _fetch_phone_button_templates(ctx: Context) -> List[Item]:
    result = ctx.client.list_phone_button_templates()
    rows = result.get("response") or []
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        ctx.progress(index, total, f"Phone button template: {name}")
        is_user_modifiable = row.get("isUserModifiable")
        is_modifiable = is_user_modifiable and str(is_user_modifiable).lower() != "false"
        items.append(Item(key=name, fields={"system": not is_modifiable}))
    return items


def _deps_phone_button_template(ctx: Context, fields: dict) -> List[Dependency]:
    name = fields.get("name")
    result = ctx.client.find_template_references(name)
    rows = result.get("response") or []
    out: List[Dependency] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dep_name = str(row.get("device_name") or "")
        if dep_name:
            out.append(Dependency(name=dep_name, type="Reference"))
    return out


def _delete_phone_button_template(ctx: Context, item: dict):
    name = item["key"]
    result = ctx.client.delete_phone_button_template(name)
    if result.get("success"):
        return True, result.get("response") or "Deleted"
    return False, result.get("error") or "Delete failed"


# -- route partitions --------------------------------------------------------

def _fetch_route_partitions(ctx: Context) -> List[Item]:
    result = ctx.client.list_RoutePartitions()
    rows = result.get("response") or []
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        ctx.progress(index, total, f"Partition: {name}")
        items.append(Item(key=name, fields={
            "description": row.get("description") or "",
        }))
    return items


def _deps_route_partition(ctx: Context, fields: dict) -> List[Dependency]:
    name = fields.get("name")
    result = ctx.client.find_partition_dependencies(name)
    return _deps_from_rows(result.get("response"))


def _delete_route_partition(ctx: Context, item: dict):
    name = item["key"]
    result = ctx.client.delete_partition(name)
    if result.get("success"):
        return True, result.get("response") or "Deleted"
    return False, result.get("error") or "Delete failed"


# -- calling search spaces ----------------------------------------------------

def _fetch_calling_search_spaces(ctx: Context) -> List[Item]:
    result = ctx.client.list_Css()
    rows = result.get("response") or []
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        ctx.progress(index, total, f"Calling search space: {name}")
        items.append(Item(key=name, fields={
            "clause": row.get("clause") or "",
            "system": name in _SYSTEM_CSS,
        }))
    return items


def _deps_calling_search_space(ctx: Context, fields: dict) -> List[Dependency]:
    name = fields.get("name")
    result = ctx.client.find_css_dependencies(name)
    return _deps_from_rows(result.get("response"))


def _delete_calling_search_space(ctx: Context, item: dict):
    name = item["key"]
    result = ctx.client.remove_Calling_Search_Space(name)
    if result.get("success"):
        return True, result.get("response") or "Deleted"
    return False, result.get("error") or "Delete failed"


# -- locations ---------------------------------------------------------------

def _fetch_locations(ctx: Context) -> List[Item]:
    result = ctx.client.list_Locations()
    rows = result.get("response") or []
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        ctx.progress(index, total, f"Location: {name}")
        items.append(Item(key=name, fields={
            "within_audio_bandwidth": row.get("withinAudioBandwidth") or "",
            "rsvp": row.get("rsvpOverAllLocations") or "",
            "system": name in _SYSTEM_LOCATIONS,
        }))
    return items


def _deps_location(ctx: Context, fields: dict) -> List[Dependency]:
    name = fields.get("name")
    result = ctx.client.find_location_dependencies(name)
    return _deps_from_rows(result.get("response"))


def _delete_location(ctx: Context, item: dict):
    name = item["key"]
    result = ctx.client.delete_location(name)
    if result.get("success"):
        return True, result.get("response") or "Deleted"
    return False, result.get("error") or "Delete failed"


# -- regions -------------------------------------------------------------------

def _fetch_regions(ctx: Context) -> List[Item]:
    result = ctx.client.list_Regions()
    rows = result.get("response") or []
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue
        ctx.progress(index, total, f"Region: {name}")
        items.append(Item(key=name, fields={
            "codec_preference_list": row.get("audioCodecPreferenceListName") or "",
            "system": name in _SYSTEM_REGIONS,
        }))
    return items


def _deps_region(ctx: Context, fields: dict) -> List[Dependency]:
    name = fields.get("name")
    result = ctx.client.find_region_dependencies(name)
    return _deps_from_rows(result.get("response"))


def _delete_region(ctx: Context, item: dict):
    name = item["key"]
    result = ctx.client.delete_region(name)
    if result.get("success"):
        return True, result.get("response") or "Deleted"
    return False, result.get("error") or "Delete failed"


# -- fetch wrappers that stash the row name into fields for deps() ---------
#
# Item.fields is all a deps() call gets (see types.py), so every fetch above
# stores whatever it needs there; deps() reads fields['name']. Since Item.key
# already carries the name, wrap each fetch below to add fields['name'] once,
# rather than repeating it in every branch above.

def _with_name_field(fetch_fn):
    def wrapped(ctx: Context) -> List[Item]:
        items = fetch_fn(ctx)
        for item in items:
            item.fields["name"] = item.key
        return items
    return wrapped


# -- registration ------------------------------------------------------------

register(ResourceSpec(
    id="cucm.softkey_templates",
    service="CUCM",
    label="Softkey Templates",
    key_label="Name",
    description="Custom softkey templates and what devices/profiles use each one.",
    columns=(
        Column(key="description", label="Description"),
        Column(key="system", label="System", kind="bool",
               help="Built-in template; cannot be deleted."),
        Column(key="deps_count", label="Dependencies", kind="deps"),
    ),
    fetch=_with_name_field(_fetch_softkey_templates),
    deps=_deps_softkey_template,
    deps_label="Devices, profiles and common device configs using this template",
    protected_keys=_softkey_protected_keys,
    actions=(
        Action(
            id="delete",
            label="Delete",
            handler=_delete_softkey_template,
            style="danger",
            confirm="Delete the selected softkey template(s)? This cannot be undone.",
            block_when_deps=True,
            removes_row=True,
        ),
    ),
))

register(ResourceSpec(
    id="cucm.phone_button_templates",
    service="CUCM",
    label="Phone Button Templates",
    key_label="Name",
    description="Phone button templates and the devices, profiles and phone "
                "types that reference them.",
    columns=(
        Column(key="system", label="System", kind="bool",
               help="Not user-modifiable; a built-in template."),
        Column(key="deps_count", label="Dependencies", kind="deps"),
    ),
    fetch=_with_name_field(_fetch_phone_button_templates),
    deps=_deps_phone_button_template,
    deps_label="Devices, device profiles and common phone configs using this template",
    actions=(
        Action(
            id="delete",
            label="Delete",
            handler=_delete_phone_button_template,
            style="danger",
            confirm="Delete the selected phone button template(s)? This cannot be undone.",
            block_when_deps=True,
            removes_row=True,
        ),
    ),
))

register(ResourceSpec(
    id="cucm.route_partitions",
    service="CUCM",
    label="Route Partitions",
    key_label="Name",
    description="Route partitions and what references each one.",
    columns=(
        Column(key="description", label="Description"),
        Column(key="deps_count", label="Dependencies", kind="deps"),
    ),
    fetch=_with_name_field(_fetch_route_partitions),
    deps=_deps_route_partition,
    deps_label="DNs, patterns and calling search spaces using this partition",
    actions=(
        Action(
            id="delete",
            label="Delete",
            handler=_delete_route_partition,
            style="danger",
            confirm="Delete the selected route partition(s)? This cannot be undone.",
            block_when_deps=True,
            removes_row=True,
        ),
    ),
))

register(ResourceSpec(
    id="cucm.calling_search_spaces",
    service="CUCM",
    label="Calling Search Spaces",
    key_label="Name",
    description="Calling search spaces, their member clause and what references them.",
    columns=(
        Column(key="clause", label="Clause", optional=True,
               help="AXL's 'clause' field for this CSS."),
        Column(key="system", label="System", kind="bool",
               help="Built-in calling search space; informational only, not delete-blocked."),
        Column(key="deps_count", label="Dependencies", kind="deps"),
    ),
    fetch=_with_name_field(_fetch_calling_search_spaces),
    deps=_deps_calling_search_space,
    deps_label="Devices, DNs, device pools and patterns using this CSS",
    actions=(
        Action(
            id="delete",
            label="Delete",
            handler=_delete_calling_search_space,
            style="danger",
            confirm="Delete the selected calling search space(s)? This cannot be undone.",
            block_when_deps=True,
            removes_row=True,
        ),
    ),
))

register(ResourceSpec(
    id="cucm.locations",
    service="CUCM",
    label="Locations",
    key_label="Name",
    description="Locations and what references each one.",
    columns=(
        Column(key="within_audio_bandwidth", label="Within Audio BW", optional=True),
        Column(key="rsvp", label="RSVP", optional=True),
        Column(key="system", label="System", kind="bool",
               help="Built-in location (Phantom/Shadow/Hub_None); informational "
                    "only, not delete-blocked."),
        Column(key="deps_count", label="Dependencies", kind="deps"),
    ),
    fetch=_with_name_field(_fetch_locations),
    deps=_deps_location,
    deps_label="Device pools, devices, trunks and other objects using this location",
    actions=(
        Action(
            id="delete",
            label="Delete",
            handler=_delete_location,
            style="danger",
            confirm="Delete the selected location(s)? This cannot be undone.",
            block_when_deps=True,
            removes_row=True,
        ),
    ),
))

register(ResourceSpec(
    id="cucm.regions",
    service="CUCM",
    label="Regions",
    key_label="Name",
    description="Regions, their codec preference list and the device pools that "
                "sit in each one.",
    columns=(
        Column(key="codec_preference_list", label="Codec Preference List", optional=True),
        Column(key="system", label="System", kind="bool",
               help="Built-in region (Default); informational only, not "
                    "delete-blocked."),
        Column(key="deps_count", label="Dependencies", kind="deps"),
    ),
    fetch=_with_name_field(_fetch_regions),
    deps=_deps_region,
    deps_label="Device pools and devices sitting in this region",
    actions=(
        Action(
            id="delete",
            label="Delete",
            handler=_delete_region,
            style="danger",
            confirm="Delete the selected region(s)? This cannot be undone.",
            block_when_deps=True,
            removes_row=True,
        ),
    ),
))
