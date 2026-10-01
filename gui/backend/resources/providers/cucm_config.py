#!/usr/bin/env python3

"""
CUCM configuration resources: device pools, advertised patterns, route
patterns, phones, directory numbers, end users, audio codec preference
lists, plus read-only views of AAR groups, call pickup groups, media
resource group lists, MOH audio sources, presence groups, voicemail
profiles and process nodes.

Operational resources reproduce what the matching CLI scripts do, through
the same cucm/ucmAPI.py methods:

* device pools         count_phones_by_device_pool / create_region_update_device_pools
* advertised patterns  add_advertisted_pattern / remove_advertisted_pattern /
                       export_advertised_patterns
* route patterns       compare_advP-RP / remedy-RP-oneoff (delete only)
* phones               update_PhoneLoad / update_LoadServer
* lines                move_DN_partition / remove_DN_EnterpriseAlternateNumber /
                       remove_DN_EntAltNum-E164AltNum
* end users            set_user_pin
* codec lists          create_audio_codec_preference_list

Row keys (Item.key), chosen to be unique within one cluster:

* device pools, phones, users, codec lists, AAR groups, MRGLs, MOH sources,
  presence groups, voicemail profiles, process nodes: the object name
  (phones: device name; users: userid).
* advertised patterns: the pattern string (CUCM enforces uniqueness of the
  pattern per cluster for advertised patterns).
* route patterns, lines, call pickup groups: "<pattern>|<partition>". A DN
  or pattern is only unique together with its partition, and the partition
  may be empty (null partition), so the key is "1000|". The handlers read
  pattern and partition back from Item.fields, never by splitting the key.

Huge resources (phones, lines, users) must be filtered. A fetch with no
filter value returns [] and posts a progress note rather than pulling every
object on the cluster; each spec says so in sync_note. Filters are
"contains" matches: a value without % is wrapped as %value%.

AXL shape notes (guesses where marked):

* serialize_object turns foreign-key fields (regionName, routePartitionName
  and similar) into {'_value_1': name, 'uuid': ...}; _val() unwraps those.
* Empty list results come back as '' from the ucmAPI wrappers, not [].
* Phone load is set with updatePhone loadInformation; load server with an
  lxml <vendorConfig><loadServer> element (as update_LoadServer.py does).
  Both reset the phone afterwards unless the "reset" box is cleared.
* Clearing alternate numbers sends the alternate number structure with all
  members None, exactly as the CLI scripts do.
* AAR group device counts and process node descriptions come from SQL and
  are best effort: if the table or column differs on a CUCM version the
  cell is left blank and the rest of the row still loads.
* The end user PIN is only ever held in ctx.params and passed to
  update_User. It is never placed in a message, and failure text has the
  PIN scrubbed before it is returned.
"""

from __future__ import annotations

import time
from csv import DictWriter
from pathlib import Path
from typing import Dict, List, Optional

from gui.backend.resources.registry import register
from gui.backend.resources.types import Action, Column, Context, Field, Item, ResourceSpec

ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "_DATA"

_TRUE = ("1", "true", "yes", "on", "y")


# -- helpers -----------------------------------------------------------------

def _val(value) -> str:
    """Unwrap an AXL foreign-key / string value into a plain string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("_value_1", "value", "name"):
            if value.get(key) not in (None, ""):
                return str(value.get(key))
        return ""
    return str(value)


def _rows(result) -> list:
    """The row list from a ucmAPI result ('' or None means no rows)."""
    resp = (result or {}).get("response")
    if isinstance(resp, list):
        return [r for r in resp if isinstance(r, dict)]
    return []


def _like(text: str) -> str:
    """Contains-match pattern for an AXL search criterion."""
    text = (text or "").strip()
    return text if "%" in text else f"%{text}%"


def _param(ctx: Context, name: str) -> str:
    return str((ctx.params or {}).get(name) or "").strip()


def _truthy(text: str) -> bool:
    return str(text or "").strip().lower() in _TRUE


def _outcome(result, ok_message: str, fail_message: str):
    """Turn a ucmAPI result dict into a handler (success, message) tuple."""
    result = result or {}
    if result.get("success"):
        return True, ok_message
    return False, str(result.get("error") or fail_message)


def _fields(item: Optional[dict]) -> dict:
    return (item or {}).get("fields") or {}


def _simple_fetch(method: str, label: str, key_field: str, build_fields):
    """Build a fetch for a list_X() that returns rows keyed by `key_field`."""
    def fetch(ctx: Context) -> List[Item]:
        result = getattr(ctx.client, method)()
        rows = _rows(result)
        if not result.get("success") and result.get("error"):
            ctx.progress(-1, None, f"{label}: {result.get('error')}")
        items: List[Item] = []
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            key = _val(row.get(key_field))
            if not key:
                continue
            ctx.progress(index, total, f"{label}: {key}")
            items.append(Item(key=key, fields=build_fields(row)))
        return items
    return fetch


# -- device pools ------------------------------------------------------------

def _fetch_device_pools(ctx: Context) -> List[Item]:
    result = ctx.client.list_DevicePools()
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Device pools: {result.get('error')}")
    rows = _rows(result)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        name = _val(row.get("name"))
        if not name:
            continue
        ctx.progress(index, total, f"Device pool: {name}")
        items.append(Item(key=name, fields={
            "region": _val(row.get("regionName")),
            "location": _val(row.get("locationName")),
            "media_resource_list": _val(row.get("mediaResourceListName")),
        }))
    return items


def _set_pool_region(ctx: Context, item: dict):
    name = (item or {}).get("key") or ""
    region = _param(ctx, "region")
    if not region:
        return False, "Choose a region"
    result = ctx.client.update_Device_Pool(name, region)
    return _outcome(result, f"{name}: region set to {region}", "Update failed")


def _delete_device_pool(ctx: Context, item: dict):
    name = (item or {}).get("key") or ""
    result = ctx.client.remove_Device_Pool(name)
    return _outcome(result, f"{name} deleted", "Delete failed")


# -- advertised patterns ------------------------------------------------------

_ADV_COLUMNS = ("description", "pattern", "patternType", "hostedRoutePSTNRule",
                "pstnFailStrip", "pstnFailPrepend")


def _advertised_rows(ctx: Context) -> list:
    result = ctx.client.list_advertised_patterns()
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Advertised patterns: {result.get('error')}")
    return _rows(result)


def _fetch_advertised_patterns(ctx: Context) -> List[Item]:
    rows = _advertised_rows(ctx)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        pattern = _val(row.get("pattern"))
        if not pattern:
            continue
        ctx.progress(index, total, f"Advertised pattern: {pattern}")
        items.append(Item(key=pattern, fields={
            "description": _val(row.get("description")),
            "pattern_type": _val(row.get("patternType")),
            "pstn_rule": _val(row.get("hostedRoutePSTNRule")),
            "pstn_fail_strip": _val(row.get("pstnFailStrip")),
            "pstn_fail_prepend": _val(row.get("pstnFailPrepend")),
        }))
    return items


def _add_advertised_pattern(ctx: Context, item):
    pattern = _param(ctx, "pattern")
    if not pattern:
        return False, "Pattern is required"
    strip = _param(ctx, "pstnFailStrip") or "0"
    result = ctx.client.add_advertised_patterns(
        description=_param(ctx, "description"),
        pattern=pattern,
        patternType=_param(ctx, "patternType") or "Enterprise Number",
        hostedRoutePSTNRule=_param(ctx, "hostedRoutePSTNRule") or "No PSTN",
        pstnFailStrip=strip,
        pstnFailPrepend=_param(ctx, "pstnFailPrepend"))
    return _outcome(result, f"{pattern} added", "Add failed")


def _delete_advertised_pattern(ctx: Context, item: dict):
    pattern = (item or {}).get("key") or ""
    result = ctx.client.remove_advertised_patterns(pattern)
    if not result.get("success") and pattern and not pattern.startswith("+"):
        # same retry as remove_advertisted_pattern.py: some are stored with a +
        retry = ctx.client.remove_advertised_patterns("+" + pattern)
        if retry.get("success"):
            return True, f"+{pattern} deleted"
    return _outcome(result, f"{pattern} deleted", "Delete failed")


def _export_advertised_patterns(ctx: Context, item):
    rows = _advertised_rows(ctx)
    if not rows:
        return False, "No advertised patterns to export"
    safe_scope = "".join(c if c.isalnum() or c in "-_." else "_" for c in ctx.scope)
    stamp = time.strftime("%Y_%m_%d-%H_%M_%S")
    filename = f"advertised_patterns-{safe_scope}-{stamp}.csv"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / filename, "w", newline="", encoding="utf8") as handle:
            writer = DictWriter(handle, fieldnames=list(_ADV_COLUMNS))
            writer.writeheader()
            for row in rows:
                writer.writerow({col: _val(row.get(col)) for col in _ADV_COLUMNS})
    except OSError as exc:
        return False, f"Could not write {filename}: {exc}"
    return True, f"Exported {len(rows)} patterns to _DATA/{filename}"


# -- route patterns ---------------------------------------------------------------

# key: "<pattern>|<partition>"; pattern and partition are also kept in fields.
def _fetch_route_patterns(ctx: Context) -> List[Item]:
    result = ctx.client.list_route_patterns()
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Route patterns: {result.get('error')}")
    rows = _rows(result)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        pattern = _val(row.get("pattern"))
        if not pattern:
            continue
        partition = _val(row.get("routePartitionName"))
        ctx.progress(index, total, f"Route pattern: {pattern}")
        items.append(Item(key=f"{pattern}|{partition}", fields={
            "pattern": pattern,
            "partition": partition,
            "description": _val(row.get("description")),
        }))
    return items


def _delete_route_pattern(ctx: Context, item: dict):
    fields = _fields(item)
    pattern = fields.get("pattern") or ""
    partition = fields.get("partition") or ""
    result = ctx.client.remove_Route_Pattern(pattern=pattern, routePartitionName=partition)
    return _outcome(result, f"{pattern} deleted", "Delete failed")


# -- phones -------------------------------------------------------------------------

_NEEDS_FILTER = "Enter a filter first; this resource is too large to list in full."


def _fetch_phones(ctx: Context) -> List[Item]:
    name = _param(ctx, "name")
    description = _param(ctx, "description")
    if not name and not description:
        ctx.progress(-1, None, "Phones: " + _NEEDS_FILTER)
        return []
    if name:
        result = ctx.client.list_Phones_search("name", _like(name))
    else:
        result = ctx.client.list_Phones_search("description", _like(description))
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Phones: {result.get('error')}")
    rows = _rows(result)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        key = _val(row.get("name"))  # device name is unique per cluster
        if not key:
            continue
        desc = _val(row.get("description"))
        if name and description and description.lower() not in desc.lower():
            continue
        ctx.progress(index, total, f"Phone: {key}")
        items.append(Item(key=key, fields={
            "description": desc,
            "model": _val(row.get("product")),
            "protocol": _val(row.get("protocol")),
            "device_pool": _val(row.get("devicePoolName")),
            "location": _val(row.get("locationName")),
            "owner": _val(row.get("ownerUserName")),
        }))
    return items


def _reset_after(ctx: Context, name: str, message: str):
    if not _truthy(_param(ctx, "reset")):
        return True, message
    reset = ctx.client.reset_Phone(name)
    if reset.get("success"):
        return True, f"{message}; reset"
    return True, f"{message}; reset failed: {reset.get('error') or 'unknown error'}"


def _set_phone_load(ctx: Context, item: dict):
    name = (item or {}).get("key") or ""
    load = _param(ctx, "load")
    if not load:
        return False, "Enter a load name"
    result = ctx.client.update_Phone(name=name, loadInformation=load)
    if not result.get("success"):
        return False, str(result.get("error") or "Update failed")
    return _reset_after(ctx, name, f"{name}: load set to {load}")


def _set_load_server(ctx: Context, item: dict):
    name = (item or {}).get("key") or ""
    server = _param(ctx, "load_server")
    if not server:
        return False, "Enter a load server"
    from lxml import etree
    vendor_config = etree.Element("vendorConfig")
    etree.SubElement(vendor_config, "loadServer").text = server
    result = ctx.client.update_Phone(name=name, vendorConfig=vendor_config)
    if not result.get("success"):
        return False, str(result.get("error") or "Update failed")
    return _reset_after(ctx, name, f"{name}: load server set to {server}")


def _reset_phone(ctx: Context, item: dict):
    name = (item or {}).get("key") or ""
    result = ctx.client.reset_Phone(name)
    return _outcome(result, f"{name} reset", "Reset failed")


# -- directory numbers ------------------------------------------------------------------

# key: "<dn>|<partition>"; dn and partition are also kept in fields.
def _fetch_lines(ctx: Context) -> List[Item]:
    dn = _param(ctx, "dn")
    partition = _param(ctx, "partition")
    if not dn and not partition:
        ctx.progress(-1, None, "Directory numbers: " + _NEEDS_FILTER)
        return []
    if dn:
        result = ctx.client.list_Line("pattern", _like(dn))
    else:
        result = ctx.client.list_Line("routePartitionName", _like(partition))
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Directory numbers: {result.get('error')}")
    rows = _rows(result)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        number = _val(row.get("pattern"))
        if not number:
            continue
        row_partition = _val(row.get("routePartitionName"))
        if dn and partition and partition.lower() not in row_partition.lower():
            continue
        ctx.progress(index, total, f"DN: {number}")
        items.append(Item(key=f"{number}|{row_partition}", fields={
            "dn": number,
            "partition": row_partition,
            "description": _val(row.get("description")),
            "alerting_name": _val(row.get("alertingName")),
        }))
    return items


def _line_ident(item: dict):
    fields = _fields(item)
    return fields.get("dn") or "", fields.get("partition") or None


def _move_line_partition(ctx: Context, item: dict):
    dn, partition = _line_ident(item)
    new_partition = _param(ctx, "new_partition")
    if not new_partition:
        return False, "Choose the new partition"
    result = ctx.client.update_Line(pattern=dn, routePartitionName=partition,
                                    newRoutePartitionName=new_partition)
    return _outcome(result, f"{dn}: moved to {new_partition}", "Move failed")


_EMPTY_ALT = {"numMask": None, "isUrgent": None, "addLocalRoutePartition": None,
              "routePartition": None, "advertiseGloballyIls": None}


def _clear_enterprise_alt(ctx: Context, item: dict):
    dn, partition = _line_ident(item)
    result = ctx.client.update_Line(pattern=dn, routePartitionName=partition,
                                    enterpriseAltNum=dict(_EMPTY_ALT))
    return _outcome(result, f"{dn}: enterprise alternate number cleared", "Clear failed")


def _clear_e164_alt(ctx: Context, item: dict):
    dn, partition = _line_ident(item)
    result = ctx.client.update_Line(pattern=dn, routePartitionName=partition,
                                    e164AltNum=dict(_EMPTY_ALT))
    return _outcome(result, f"{dn}: +E.164 alternate number cleared", "Clear failed")


# -- end users --------------------------------------------------------------------------------

def _fetch_users(ctx: Context) -> List[Item]:
    userid = _param(ctx, "userid")
    last_name = _param(ctx, "last_name")
    if not userid and not last_name:
        ctx.progress(-1, None, "End users: " + _NEEDS_FILTER)
        return []
    if userid:
        result = ctx.client.list_Users("userid", _like(userid))
    else:
        result = ctx.client.list_Users("lastName", _like(last_name))
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"End users: {result.get('error')}")
    rows = _rows(result)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        key = _val(row.get("userid"))  # userid is unique per cluster
        if not key:
            continue
        row_last = _val(row.get("lastName"))
        if userid and last_name and last_name.lower() not in row_last.lower():
            continue
        ctx.progress(index, total, f"User: {key}")
        items.append(Item(key=key, fields={
            "first_name": _val(row.get("firstName")),
            "last_name": row_last,
            "department": _val(row.get("department")),
            "telephone": _val(row.get("telephoneNumber")),
        }))
    return items


def _set_user_pin(ctx: Context, item: dict):
    userid = (item or {}).get("key") or ""
    pin = str((ctx.params or {}).get("pin") or "")
    if not pin:
        return False, "Enter a PIN"
    result = ctx.client.update_User(userid=userid, pin=pin)
    if result.get("success"):
        return True, f"{userid}: PIN set"
    error = str(result.get("error") or "Update failed").replace(pin, "***")
    return False, error


# -- audio codec preference lists -----------------------------------------------------------

def _fetch_codec_lists(ctx: Context) -> List[Item]:
    result = ctx.client.list_AudioCodecPreferenceLists()
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Codec preference lists: {result.get('error')}")
    rows = _rows(result)
    items: List[Item] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        name = _val(row.get("name"))
        if not name:
            continue
        ctx.progress(index, total, f"Codec preference list: {name}")
        items.append(Item(key=name, fields={"description": _val(row.get("description"))}))
    return items


def _add_codec_list(ctx: Context, item):
    name = _param(ctx, "name")
    codecs = [c.strip() for c in _param(ctx, "codecs").split(",") if c.strip()]
    if not name:
        return False, "Name is required"
    if not codecs:
        return False, "Enter at least one codec"
    result = ctx.client.add_audio_codec_preference_list(
        name=name, codec_list=codecs, description=_param(ctx, "description"))
    return _outcome(result, f"{name} added ({', '.join(codecs)})", "Add failed")


# -- read-only resources ----------------------------------------------------------------------

def _fetch_aar_groups(ctx: Context) -> List[Item]:
    items = _simple_fetch("list_AarGroups", "AAR group", "name", lambda row: {"device_count": None})(ctx)
    counts: Dict[str, int] = {}
    try:
        # best effort; table/column names are a guess for the CUCM schema
        sql = ctx.client.execute_sql_query(
            "select a.name as name, count(d.pkid) as cnt from aargroup a "
            "left join device d on d.fkaargroup = a.pkid group by a.name")
        for row in _rows(sql):
            counts[str(row.get("name") or "")] = int(row.get("cnt") or 0)
    except Exception:
        counts = {}
    for it in items:
        it.fields["device_count"] = counts.get(it.key)
    return items


def _fetch_call_pickup_groups(ctx: Context) -> List[Item]:
    # key: "<pattern>|<partition>" (a pickup group number is unique per partition)
    result = ctx.client.list_CallPickupGroup()
    if not result.get("success") and result.get("error"):
        ctx.progress(-1, None, f"Call pickup groups: {result.get('error')}")
    items: List[Item] = []
    rows = _rows(result)
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        pattern = _val(row.get("pattern"))
        if not pattern:
            continue
        partition = _val(row.get("routePartitionName"))
        ctx.progress(index, total, f"Call pickup group: {pattern}")
        items.append(Item(key=f"{pattern}|{partition}", fields={
            "pattern": pattern,
            "partition": partition,
            "description": _val(row.get("description")),
        }))
    return items


def _fetch_process_nodes(ctx: Context) -> List[Item]:
    try:
        result = ctx.client.listProcessNodes()
    except Exception as exc:     # listProcessNodes does not catch zeep faults itself
        ctx.progress(-1, None, f"Process nodes: {exc}")
        return []
    names = result.get("response") if isinstance(result, dict) else None
    if not isinstance(names, list):
        if isinstance(result, dict) and result.get("error"):
            ctx.progress(-1, None, f"Process nodes: {result.get('error')}")
        return []
    descriptions: Dict[str, str] = {}
    try:
        # best effort; processnode.description is a guess for the CUCM schema
        sql = ctx.client.execute_sql_query("select name, description from processnode")
        for row in _rows(sql):
            descriptions[str(row.get("name") or "")] = str(row.get("description") or "")
    except Exception:
        descriptions = {}
    items: List[Item] = []
    total = len(names)
    for index, name in enumerate(names, start=1):
        name = _val(name)
        if not name:
            continue
        ctx.progress(index, total, f"Process node: {name}")
        items.append(Item(key=name, fields={"description": descriptions.get(name, "")}))
    return items


# -- registration -------------------------------------------------------------------------------

register(ResourceSpec(
    id="cucm.device_pools",
    service="CUCM",
    label="Device Pools",
    key_label="Name",
    description="Device pools with their region, location and media resource group list.",
    columns=(
        Column(key="region", label="Region"),
        Column(key="location", label="Location"),
        Column(key="media_resource_list", label="Media resource list"),
    ),
    fetch=_fetch_device_pools,
    actions=(
        Action(id="set_region", label="Set region", handler=_set_pool_region,
               fields=(Field(name="region", label="Region", kind="select", required=True,
                             options_from="cucm.regions:name"),),
               help="Point the selected device pools at another region."),
        Action(id="delete", label="Delete", handler=_delete_device_pool, style="danger",
               confirm="Delete the selected device pool(s)? This cannot be undone.",
               removes_row=True),
    ),
))

register(ResourceSpec(
    id="cucm.advertised_patterns",
    service="CUCM",
    label="Advertised Patterns",
    key_label="Pattern",
    description="Hosted DN and PSTN advertised patterns (Intercluster Lookup Service).",
    columns=(
        Column(key="description", label="Description"),
        Column(key="pattern_type", label="Type", kind="badge"),
        Column(key="pstn_rule", label="PSTN rule"),
        Column(key="pstn_fail_strip", label="PSTN strip", kind="number", optional=True),
        Column(key="pstn_fail_prepend", label="PSTN prepend", optional=True),
    ),
    fetch=_fetch_advertised_patterns,
    actions=(
        Action(id="add", label="Add pattern", handler=_add_advertised_pattern,
               scope_mode="form", style="primary",
               fields=(
                   Field(name="pattern", label="Pattern", required=True),
                   Field(name="description", label="Description"),
                   Field(name="patternType", label="Pattern type", kind="select",
                         default="Enterprise Number",
                         options=("Enterprise Number", "+E.164 Number")),
                   Field(name="hostedRoutePSTNRule", label="PSTN rule", kind="select",
                         default="No PSTN",
                         options=("No PSTN", "Use pattern", "Specify")),
                   Field(name="pstnFailStrip", label="PSTN fail strip digits", kind="number",
                         default="0"),
                   Field(name="pstnFailPrepend", label="PSTN fail prepend"),
               )),
        Action(id="delete", label="Delete", handler=_delete_advertised_pattern,
               style="danger", removes_row=True,
               confirm="Delete the selected advertised pattern(s)?"),
        Action(id="export", label="Export CSV", handler=_export_advertised_patterns,
               scope_mode="none", resync_after=False,
               help="Writes every advertised pattern on the cluster to a CSV in _DATA."),
    ),
))

register(ResourceSpec(
    id="cucm.route_patterns",
    service="CUCM",
    label="Route Patterns",
    key_label="Pattern | partition",
    description="Route patterns and the partition each one lives in.",
    columns=(
        Column(key="pattern", label="Pattern"),
        Column(key="partition", label="Partition"),
        Column(key="description", label="Description"),
    ),
    fetch=_fetch_route_patterns,
    actions=(
        Action(id="delete", label="Delete", handler=_delete_route_pattern, style="danger",
               confirm="Delete the selected route pattern(s)? This cannot be undone.",
               removes_row=True),
    ),
))

register(ResourceSpec(
    id="cucm.phones",
    service="CUCM",
    label="Phones",
    key_label="Device name",
    description="Phones matching a device name or description search.",
    columns=(
        Column(key="description", label="Description"),
        Column(key="model", label="Model"),
        Column(key="protocol", label="Protocol", optional=True),
        Column(key="device_pool", label="Device pool"),
        Column(key="location", label="Location", optional=True),
        Column(key="owner", label="Owner", optional=True),
    ),
    fetch=_fetch_phones,
    filters=(
        Field(name="name", label="Device name contains", placeholder="SEP00"),
        Field(name="description", label="Description contains"),
    ),
    sync_note="A filter is required: with no device name or description the sync "
              "returns nothing, because a cluster can have tens of thousands of phones.",
    actions=(
        Action(id="set_phone_load", label="Set phone load", handler=_set_phone_load,
               fields=(
                   Field(name="load", label="Load name", required=True,
                         placeholder="sip88xx.14-4-1-0001-36"),
                   Field(name="reset", label="Reset the phone afterwards", kind="bool",
                         default="true"),
               )),
        Action(id="set_load_server", label="Set load server", handler=_set_load_server,
               fields=(
                   Field(name="load_server", label="Load server", required=True,
                         default="cloudupgrader.webex.com"),
                   Field(name="reset", label="Reset the phone afterwards", kind="bool",
                         default="true"),
               )),
        Action(id="reset", label="Reset", handler=_reset_phone,
               confirm="Reset the selected phone(s)? Active calls will drop."),
    ),
))

register(ResourceSpec(
    id="cucm.lines",
    service="CUCM",
    label="Directory Numbers",
    key_label="DN | partition",
    description="Directory numbers matching a pattern or partition search.",
    columns=(
        Column(key="dn", label="Directory number"),
        Column(key="partition", label="Partition"),
        Column(key="description", label="Description"),
        Column(key="alerting_name", label="Alerting name", optional=True),
    ),
    fetch=_fetch_lines,
    filters=(
        Field(name="dn", label="DN contains", placeholder="1000"),
        Field(name="partition", label="Partition contains"),
    ),
    sync_note="A filter is required: with no DN or partition the sync returns "
              "nothing, because a cluster can have a very large number of lines.",
    actions=(
        Action(id="move_partition", label="Move partition", handler=_move_line_partition,
               fields=(Field(name="new_partition", label="New partition", kind="select",
                             required=True, options_from="cucm.route_partitions:name"),)),
        Action(id="clear_enterprise_alt_number", label="Clear enterprise alt number",
               handler=_clear_enterprise_alt,
               confirm="Clear the enterprise alternate number on the selected DN(s)?"),
        Action(id="clear_e164_alt_number", label="Clear +E.164 alt number",
               handler=_clear_e164_alt,
               confirm="Clear the +E.164 alternate number on the selected DN(s)?"),
    ),
))

register(ResourceSpec(
    id="cucm.users",
    service="CUCM",
    label="End Users",
    key_label="User ID",
    description="End users matching a user ID or last name search.",
    columns=(
        Column(key="first_name", label="First name"),
        Column(key="last_name", label="Last name"),
        Column(key="department", label="Department", optional=True),
        Column(key="telephone", label="Telephone", optional=True),
    ),
    fetch=_fetch_users,
    filters=(
        Field(name="userid", label="User ID contains"),
        Field(name="last_name", label="Last name contains"),
    ),
    sync_note="A filter is required: with no user ID or last name the sync "
              "returns nothing, because a cluster can have a very large number of users.",
    actions=(
        Action(id="set_pin", label="Set PIN", handler=_set_user_pin,
               confirm="Set the PIN on the selected user(s)?",
               fields=(Field(name="pin", label="New PIN", kind="secret", required=True),),
               help="The PIN is never shown, logged or stored."),
    ),
))

register(ResourceSpec(
    id="cucm.audio_codec_preference_lists",
    service="CUCM",
    label="Audio Codec Preference Lists",
    key_label="Name",
    description="Audio codec preference lists used by regions.",
    columns=(Column(key="description", label="Description"),),
    fetch=_fetch_codec_lists,
    actions=(
        Action(id="add", label="Add list", handler=_add_codec_list, scope_mode="form",
               style="primary",
               fields=(
                   Field(name="name", label="Name", required=True),
                   Field(name="description", label="Description"),
                   Field(name="codecs", label="Codecs, highest priority first", required=True,
                         placeholder="G.722, G.711-ulaw, G.729",
                         help="Comma separated. Common: G.711-ulaw, G.711-alaw, G.729, "
                              "G.722, G.722.1, iLBC, Opus."),
               )),
    ),
))

# -- read-only -----------------------------------------------------------------------------------

register(ResourceSpec(
    id="cucm.aar_groups", service="CUCM", label="AAR Groups", key_label="Name",
    description="Automated alternate routing groups.",
    columns=(Column(key="device_count", label="Devices", kind="number",
                    help="Devices assigned to the group (best effort SQL count)."),),
    fetch=_fetch_aar_groups,
))

register(ResourceSpec(
    id="cucm.call_pickup_groups", service="CUCM", label="Call Pickup Groups",
    key_label="Pattern | partition",
    description="Call pickup groups.",
    columns=(
        Column(key="pattern", label="Pattern"),
        Column(key="partition", label="Partition"),
        Column(key="description", label="Description"),
    ),
    fetch=_fetch_call_pickup_groups,
))

register(ResourceSpec(
    id="cucm.media_resource_group_lists", service="CUCM",
    label="Media Resource Group Lists", key_label="Name",
    description="Media resource group lists and the groups they contain.",
    columns=(Column(key="groups", label="Media resource groups"),),
    fetch=_simple_fetch("list_MediaResourceLists", "Media resource group list", "name",
                        lambda row: {"groups": _val(row.get("clause"))}),
))

register(ResourceSpec(
    id="cucm.moh_audio_sources", service="CUCM", label="MOH Audio Sources",
    key_label="Name", description="Music on hold audio sources.",
    columns=(Column(key="source_id", label="Source ID", kind="number"),),
    fetch=_simple_fetch("list_MohAudioSources", "MOH audio source", "name",
                        lambda row: {"source_id": int(_val(row.get("sourceId"))) if _val(row.get("sourceId")).isdigit() else None}),
))

register(ResourceSpec(
    id="cucm.presence_groups", service="CUCM", label="Presence Groups",
    key_label="Name", description="Presence groups.",
    columns=(Column(key="description", label="Description"),),
    fetch=_simple_fetch("list_PresenceGroups", "Presence group", "name",
                        lambda row: {"description": _val(row.get("description"))}),
))

register(ResourceSpec(
    id="cucm.voicemail_profiles", service="CUCM", label="Voicemail Profiles",
    key_label="Name", description="Voicemail profiles.",
    columns=(Column(key="description", label="Description"),),
    fetch=_simple_fetch("list_VoiceMailProfiles", "Voicemail profile", "name",
                        lambda row: {"description": _val(row.get("description"))}),
))

register(ResourceSpec(
    id="cucm.process_nodes", service="CUCM", label="Process Nodes",
    key_label="Name", description="Call processing (CUCM Voice/Video) nodes in the cluster.",
    columns=(Column(key="description", label="Description"),),
    fetch=_fetch_process_nodes,
))
