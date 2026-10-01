#!/usr/bin/env python3

"""
Webex resource provider for the web GUI.

Registers the resources that back the Webex pages in gui/backend/pages.py:
locations, people, workspaces, devices, PSTN numbers, call queues, hunt
groups and org user groups. Each fetch()/action pair here is the GUI
counterpart of one or more scripts in webex/*.py, rebuilt against the
shared webex/webexAPI.py client instead of ad hoc requests calls.

API families used (see CLAUDE.md and webex/webexAPI.py):
* Calling config - GET/PUT /telephony/config/... (locations, numbers,
  queues, hunt groups, virtual lines, redSky status). This is what this
  repo's integration has scope for.
* Core people/workspaces/devices/groups/licenses - /people, /workspaces,
  /devices, /groups, /licenses, /workspaceLocations.
* This module never calls the core /v1/locations family (spark-admin:
  locations_read) that several of the older webex/*.py scripts used for
  location name lookups (getLocationID()) - that scope is not granted to
  this integration. Location name -> id resolution here always goes
  through webexAPI.list_locations() (/telephony/config/locations), the
  same family DisableRedSkyOnLocations.py and ModifyNumbers.py's
  getCallingLocationID() use.

Key choices per resource (Item.key must be stable and unique per scope):
* locations: keyed by name. Webex enforces unique location names per org,
  and the name is what every create/update script looks the location up
  by, so it reads better than the id. The id still travels in fields
  ('location_id') for handlers that need it.
* people: keyed by primary email. Emails are unique per Webex person and
  it is the natural search key; the Webex person id travels in
  fields['id'].
* groups: keyed by displayName (org group names are unique); id in
  fields['id'].
* workspaces, devices, numbers, call queues, hunt groups: none of these
  have a human name that is guaranteed unique across the whole org (two
  workspaces can share a display name, two queues in different locations
  can share a name), so these are keyed by their Webex id and the name
  lives in fields. Numbers are the one exception worth calling out: the
  E.164 number is both unique and the natural key, so it is the key and
  is therefore NOT repeated as a column (see types.py: "do not add a
  column for the key itself").

Every handler recovers the Webex id it needs from item['fields'] (or, for
resources keyed by the id itself, from item['key']) and returns
(bool, str). None ever raises for an expected API failure.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from gui.backend.resources.registry import register
from gui.backend.resources.types import Action, Column, Context, Field, Item, ResourceSpec

# -- small shared helpers --------------------------------------------------


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _strip_blanks(value):
    """Recursively drop dict keys (and list entries) that are None/''/{}/[].

    Webex's config APIs are picky about being sent an empty string or null
    for a field that was simply left blank on the form, so every payload
    builder below runs through this before posting.
    """
    if isinstance(value, dict):
        cleaned = {k: _strip_blanks(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, "", {}, [])}
    if isinstance(value, list):
        return [_strip_blanks(v) for v in value]
    return value


def _location_maps(ctx: Context) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(name_by_id, id_by_name) for every calling location in the org."""
    result = ctx.client.list_locations()
    name_by_id: Dict[str, str] = {}
    id_by_name: Dict[str, str] = {}
    if result.get("success"):
        for loc in result.get("response") or []:
            loc_id, name = loc.get("id", ""), loc.get("name", "")
            if loc_id:
                name_by_id[loc_id] = name
            if name:
                id_by_name[name] = loc_id
    return name_by_id, id_by_name


def _resolve_agent(ctx: Context, entry: str):
    """One agent CSV-style entry (email or extension/DN) -> {'id': ...} or None."""
    entry = entry.strip()
    if not entry:
        return None
    wx = ctx.client
    if entry.replace("+", "").isdigit():
        result = wx.list_virtual_lines(params={"phoneNumber": entry})
        if result.get("success") and result.get("response"):
            return {"id": result["response"][0].get("id", "")}
        return None
    result = wx.list_people(params={"email": entry})
    if result.get("success") and result.get("response"):
        return {"id": result["response"][0].get("id", "")}
    return None


def _resolve_agents(ctx: Context, raw_text: str) -> List[dict]:
    """A textarea of emails/extensions (comma or newline separated) -> agent list."""
    entries = [e.strip() for e in (raw_text or "").replace(",", "\n").splitlines() if e.strip()]
    agents = []
    for entry in entries:
        agent = _resolve_agent(ctx, entry)
        if agent and agent.get("id"):
            agents.append(agent)
        else:
            ctx.log(f"Could not resolve agent {entry!r}; skipping")
    return agents


# -- webex.locations --------------------------------------------------------


def fetch_locations(ctx: Context) -> List[Item]:
    wx = ctx.client
    result = wx.list_locations()
    if not result.get("success"):
        ctx.log(f"Failed to list locations: {result.get('error')}")
        return []
    locations = result.get("response") or []
    items: List[Item] = []
    total = len(locations)
    for index, loc in enumerate(locations, start=1):
        if ctx.cancelled():
            break
        loc_id = loc.get("id", "")
        name = loc.get("name", "") or loc_id
        ctx.progress(index, total, f"Location: {name}")
        address = loc.get("address") or {}

        detail = {}
        if loc_id:
            detail_result = wx.get_location(loc_id)
            if detail_result.get("success"):
                detail = detail_result.get("response") or {}

        redsky_provider = ""
        if loc_id:
            redsky_result = wx.get_redsky_status(loc_id)
            if redsky_result.get("success"):
                status = (redsky_result.get("response") or {}).get("complianceStatus", "")
                if status == "OPTED_IN":
                    redsky_provider = "RedSky"
                elif status:
                    redsky_provider = "Other"

        # Field names for timezone/language/main number on the location
        # detail object are a best guess (this cannot be checked against a
        # live org); .get() with fallbacks keeps a wrong guess harmless.
        main_number = ((detail.get("callingLineId") or {}).get("phoneNumber")
                       or loc.get("mainNumber") or "")
        items.append(Item(
            key=name,
            fields={
                "location_id": loc_id,
                "city": address.get("city", ""),
                "country": address.get("country", ""),
                "timezone": detail.get("timeZone", loc.get("timeZone", "")),
                "announcement_language": detail.get("announcementLanguage",
                                                     detail.get("preferredLanguage", "")),
                "emergency_provider": redsky_provider,
                "main_number": main_number,
            },
        ))
    return items


def act_disable_redsky(ctx: Context, item: dict):
    fields = item["fields"]
    loc_id = fields.get("location_id") or item.get("key")
    if not loc_id:
        return False, "Missing location id"
    result = ctx.client.set_redsky_status(loc_id, opted_out=True)
    if not result.get("success"):
        return False, result.get("error") or "Failed to disable RedSky"
    return True, "RedSky routing disabled"


register(ResourceSpec(
    id="webex.locations",
    service="WEBEX",
    label="Calling Locations",
    key_label="Name",
    description="Webex Calling locations in the org.",
    columns=[
        Column("city", "City"),
        Column("country", "Country"),
        Column("timezone", "Timezone", optional=True),
        Column("announcement_language", "Announcement Language", optional=True),
        Column("emergency_provider", "Emergency Calling", kind="badge",
              tone_map={"RedSky": "warn", "Other": "ok"}),
        Column("main_number", "Main Number", optional=True),
    ],
    fetch=fetch_locations,
    actions=[
        Action(
            id="disable_redsky",
            label="Disable RedSky",
            handler=act_disable_redsky,
            scope_mode="selection",
            style="secondary",
            confirm="Turn RedSky emergency-calling routing off for these locations?",
            help="Sets complianceStatus to OPTED_OUT, per DisableRedSkyOnLocations.py.",
        ),
    ],
))


# -- webex.people -----------------------------------------------------------


def fetch_people(ctx: Context) -> List[Item]:
    wx = ctx.client
    email = (ctx.params.get("email") or "").strip()
    display_name = (ctx.params.get("display_name") or "").strip()
    location_name = (ctx.params.get("location") or "").strip()

    if not email and not display_name and not location_name:
        ctx.progress(0, 0, "No filter given; an org can have tens of thousands of users. "
                           "Enter an email, name or location filter above and sync again.")
        return []

    params: Dict[str, str] = {}
    if email:
        params["email"] = email
    if display_name:
        params["displayName"] = display_name
    location_id = ""
    if location_name:
        _, id_by_name = _location_maps(ctx)
        location_id = id_by_name.get(location_name, "")
        if not location_id:
            ctx.log(f"Location {location_name!r} not found")
            return []
        params["locationId"] = location_id

    result = wx.list_people(params=params)
    if not result.get("success"):
        ctx.log(f"Failed to list people: {result.get('error')}")
        return []

    name_by_id, _ = _location_maps(ctx)
    items: List[Item] = []
    for person in result.get("response") or []:
        if ctx.cancelled():
            break
        emails = person.get("emails") or []
        primary_email = emails[0] if emails else person.get("id", "")
        phone_numbers = person.get("phoneNumbers") or []
        phone_number = next((p.get("value", "") for p in phone_numbers
                            if p.get("type") == "work"), "")
        person_location_id = person.get("locationId", "")
        items.append(Item(
            key=primary_email,
            fields={
                "id": person.get("id", ""),
                "display_name": person.get("displayName", ""),
                "first_name": person.get("firstName", ""),
                "last_name": person.get("lastName", ""),
                "location": name_by_id.get(person_location_id, ""),
                "location_id": person_location_id,
                "extension": person.get("extension", ""),
                "phone_number": phone_number,
                "department": person.get("department", ""),
            },
        ))
    return items


def act_delete_person(ctx: Context, item: dict):
    person_id = item["fields"].get("id") or ""
    if not person_id:
        return False, "Missing user id"
    result = ctx.client.delete_person(person_id)
    if not result.get("success"):
        return False, result.get("error") or "Failed to delete user"
    return True, "User deleted"


def act_reset_pin(ctx: Context, item: dict):
    person_id = item["fields"].get("id") or ""
    pin = ctx.params.get("pin") or ""
    if not person_id or not pin:
        return False, "Missing user id or PIN"
    result = ctx.client.reset_person_pin(person_id, pin)
    if not result.get("success"):
        return False, result.get("error") or "Failed to reset PIN"
    return True, "Voicemail PIN reset"          # never echo the PIN itself


def act_set_call_forward_all(ctx: Context, item: dict):
    person_id = item["fields"].get("id") or ""
    destination = (ctx.params.get("destination") or "").strip()
    if not person_id or not destination:
        return False, "Missing user id or destination"
    always = {"enabled": True, "destination": destination, "destinationVoicemailEnabled": False}
    if _truthy(ctx.params.get("ring_reminder")):
        # Ring reminder is only sent when asked for: it is not confirmed to
        # exist on a person's callForwarding object in every org, and
        # omitting the key entirely is harmless where it does not apply.
        always["ringReminderEnabled"] = True
    result = ctx.client.set_person_call_forwarding(person_id, {"callForwarding": {"always": always}})
    if not result.get("success"):
        return False, result.get("error") or "Failed to set Call Forward All"
    return True, f"Call Forward All set to {destination}"


def act_clear_call_forward_all(ctx: Context, item: dict):
    person_id = item["fields"].get("id") or ""
    if not person_id:
        return False, "Missing user id"
    payload = {"callForwarding": {"always": {"enabled": False, "destination": ""}}}
    result = ctx.client.set_person_call_forwarding(person_id, payload)
    if not result.get("success"):
        return False, result.get("error") or "Failed to clear Call Forward All"
    return True, "Call Forward All cleared"


def act_add_to_group(ctx: Context, item: dict):
    wx = ctx.client
    person_id = item["fields"].get("id") or ""
    group_name = (ctx.params.get("group") or "").strip()
    if not person_id or not group_name:
        return False, "Missing user id or group"
    groups_result = wx.list_groups()
    if not groups_result.get("success"):
        return False, groups_result.get("error") or "Failed to list groups"
    match = next((g for g in groups_result.get("response") or []
                 if g.get("displayName") == group_name), None)
    if not match:
        return False, f"Group {group_name!r} not found"
    detail = wx.get_group(match["id"], include_members=True)
    if not detail.get("success"):
        return False, detail.get("error") or "Failed to read group"
    members = list((detail.get("response") or {}).get("members") or [])
    if not any(m.get("id") == person_id for m in members):
        members.append({"id": person_id})
    result = wx.patch_group(match["id"], members)
    if not result.get("success"):
        return False, result.get("error") or "Failed to update group"
    return True, f"Added to group {group_name}"


register(ResourceSpec(
    id="webex.people",
    service="WEBEX",
    label="Users",
    key_label="Email",
    description="People in the org.",
    sync_note="An org can have tens of thousands of users: sync only runs a search when "
              "an email, name or location filter is given, and returns nothing otherwise.",
    filters=[
        Field("email", "Email contains", kind="text"),
        Field("display_name", "Name contains", kind="text"),
        Field("location", "Location", kind="select", options_from="webex.locations:name"),
    ],
    columns=[
        Column("display_name", "Display Name"),
        Column("first_name", "First Name", optional=True),
        Column("last_name", "Last Name", optional=True),
        Column("location", "Location"),
        Column("extension", "Extension", optional=True),
        Column("phone_number", "Phone Number", optional=True),
        Column("department", "Department", optional=True),
    ],
    fetch=fetch_people,
    actions=[
        Action(
            id="delete",
            label="Delete",
            handler=act_delete_person,
            scope_mode="selection",
            style="danger",
            confirm="Delete these users from Control Hub? This cannot be undone.",
            removes_row=True,
            help="Based on BulkDeleteUsers.py.",
        ),
        Action(
            id="reset_pin",
            label="Reset Voicemail PIN",
            handler=act_reset_pin,
            scope_mode="selection",
            style="secondary",
            confirm="Reset the voicemail PIN for these users?",
            fields=[Field("pin", "New PIN", kind="secret", required=True)],
            help="Based on ResetUserPin.py.",
        ),
        Action(
            id="set_call_forward_all",
            label="Set Call Forward All",
            handler=act_set_call_forward_all,
            scope_mode="selection",
            style="secondary",
            fields=[
                Field("destination", "Forward to", kind="text", required=True),
                Field("ring_reminder", "Play a ring reminder", kind="bool"),
            ],
            help="Based on CallFowardAll.py.",
        ),
        Action(
            id="clear_call_forward_all",
            label="Clear Call Forward All",
            handler=act_clear_call_forward_all,
            scope_mode="selection",
            style="secondary",
            confirm="Turn off Call Forward All for these users?",
            help="Based on CallFowardAll-Remove.py.",
        ),
        Action(
            id="add_to_group",
            label="Add to Group",
            handler=act_add_to_group,
            scope_mode="selection",
            style="secondary",
            fields=[Field("group", "Group", kind="select", required=True,
                         options_from="webex.groups:name")],
            help="Based on UpdateUserGroups.py.",
        ),
    ],
))


# -- webex.workspaces ---------------------------------------------------------


def fetch_workspaces(ctx: Context) -> List[Item]:
    wx = ctx.client
    result = wx.list_workspaces()
    if not result.get("success"):
        ctx.log(f"Failed to list workspaces: {result.get('error')}")
        return []
    name_by_id, _ = _location_maps(ctx)
    items: List[Item] = []
    for ws in result.get("response") or []:
        calling = ((ws.get("calling") or {}).get("webexCalling") or {})
        calling_location_id = calling.get("locationId", "")
        items.append(Item(
            key=ws.get("id", ""),
            fields={
                "display_name": ws.get("displayName", ""),
                "type": ws.get("type", ""),
                "location": name_by_id.get(calling_location_id, ""),
                "phone_number": calling.get("phoneNumber", ""),
                "extension": calling.get("extension", ""),
                "capacity": ws.get("capacity", ""),
            },
        ))
    return items


def act_create_workspace(ctx: Context, item):
    wx = ctx.client
    p = ctx.params
    name = (p.get("name") or "").strip()
    if not name:
        return False, "Name is required"

    workspace_location_name = (p.get("workspace_location") or "").strip()
    workspace_location_id = ""
    if workspace_location_name:
        wl_result = wx.list_workspace_locations(params={"displayName": workspace_location_name})
        if wl_result.get("success") and wl_result.get("response"):
            workspace_location_id = wl_result["response"][0].get("id", "")

    location_name = (p.get("location") or "").strip()
    phone_number = (p.get("phone_number") or "").strip()
    extension = (p.get("extension") or "").strip()

    webex_calling = {}
    if location_name or phone_number or extension:
        _, id_by_name = _location_maps(ctx)
        calling_location_id = id_by_name.get(location_name, "")
        if calling_location_id:
            webex_calling["locationId"] = calling_location_id
        if phone_number:
            webex_calling["phoneNumber"] = phone_number if phone_number.startswith("+") \
                else f"+{phone_number}"
        if extension:
            webex_calling["extension"] = extension

    payload = _strip_blanks({
        "displayName": name,
        "workspaceLocationId": workspace_location_id,
        "type": (p.get("type") or "").strip(),
        "calling": {"type": "webexCalling", "webexCalling": webex_calling} if webex_calling else {},
    })
    result = wx.create_workspace(payload)
    if not result.get("success"):
        return False, result.get("error") or "Failed to create workspace"
    return True, f"Workspace {name!r} created"


def act_add_device(ctx: Context, item: dict):
    workspace_id = item.get("key") or ""
    if not workspace_id:
        return False, "Missing workspace id"
    result = ctx.client.create_activation_code(workspace_id=workspace_id)
    if not result.get("success"):
        return False, result.get("error") or "Failed to generate activation code"
    code = (result.get("response") or {}).get("activationCode", "")
    return True, (f"Activation code: {code}" if code else "Activation code generated")


def act_delete_workspace(ctx: Context, item: dict):
    workspace_id = item.get("key") or ""
    if not workspace_id:
        return False, "Missing workspace id"
    result = ctx.client.delete_workspace(workspace_id)
    if not result.get("success"):
        return False, result.get("error") or "Failed to delete workspace"
    return True, "Workspace deleted"


register(ResourceSpec(
    id="webex.workspaces",
    service="WEBEX",
    label="Workspaces",
    key_label="ID",
    description="Workspaces (shared-space calling devices) in the org.",
    columns=[
        Column("display_name", "Name"),
        Column("type", "Type", optional=True),
        Column("location", "Location"),
        Column("phone_number", "Phone Number", optional=True),
        Column("extension", "Extension", optional=True),
        Column("capacity", "Capacity", kind="number", optional=True),
    ],
    fetch=fetch_workspaces,
    actions=[
        Action(
            id="create",
            label="Create Workspace",
            handler=act_create_workspace,
            scope_mode="form",
            style="primary",
            fields=[
                Field("name", "Name", kind="text", required=True),
                Field("workspace_location", "Workspace Location (building)", kind="text",
                     help="Name of the workspace location, if the org uses them."),
                Field("type", "Type", kind="select",
                     options=["notSet", "focus", "huddle", "meetingRoom", "openSpace",
                             "desk", "other"]),
                Field("location", "Calling Location", kind="select",
                     options_from="webex.locations:name"),
                Field("phone_number", "Phone Number"),
                Field("extension", "Extension"),
            ],
            help="Based on CreateWorkspace.py.",
        ),
        Action(
            id="add_device",
            label="Generate Activation Code",
            handler=act_add_device,
            scope_mode="selection",
            style="secondary",
            help="Generates a device activation code for the chosen workspaces "
                "(POST /devices/activationCode).",
        ),
        Action(
            id="delete",
            label="Delete",
            handler=act_delete_workspace,
            scope_mode="selection",
            style="danger",
            confirm="Delete these workspaces?",
            removes_row=True,
        ),
    ],
))


# -- webex.devices ------------------------------------------------------------


def fetch_devices(ctx: Context) -> List[Item]:
    wx = ctx.client
    result = wx.list_devices()
    if not result.get("success"):
        ctx.log(f"Failed to list devices: {result.get('error')}")
        return []
    ws_result = wx.list_workspaces()
    ws_names = {w.get("id", ""): w.get("displayName", "")
               for w in (ws_result.get("response") or [])} if ws_result.get("success") else {}
    items: List[Item] = []
    for dev in result.get("response") or []:
        workspace_id = dev.get("workspaceId", "")
        person_id = dev.get("personId", "")
        # A person-owned device only shows the raw person id here: mapping
        # it to a display name would mean a full people sync on every
        # devices sync, which is too costly for a large org.
        assigned_to = ws_names.get(workspace_id, "") if workspace_id else person_id
        items.append(Item(
            key=dev.get("id", ""),
            fields={
                "display_name": dev.get("displayName", ""),
                "product": dev.get("product", ""),
                "type": dev.get("type", ""),
                "connection_status": dev.get("connectionStatus", ""),
                "mac": dev.get("mac", ""),
                "assigned_to": assigned_to,
            },
        ))
    return items


def act_delete_device(ctx: Context, item: dict):
    device_id = item.get("key") or ""
    if not device_id:
        return False, "Missing device id"
    result = ctx.client.delete_device(device_id)
    if not result.get("success"):
        return False, result.get("error") or "Failed to delete device"
    return True, "Device deleted"


register(ResourceSpec(
    id="webex.devices",
    service="WEBEX",
    label="Devices",
    key_label="ID",
    description="Devices registered in the org (read-only list, plus delete).",
    columns=[
        Column("display_name", "Name"),
        Column("product", "Product", optional=True),
        Column("type", "Type", optional=True),
        Column("connection_status", "Connection", kind="badge",
              tone_map={"connected": "ok", "disconnected": "danger", "connected_with_issues": "warn"}),
        Column("mac", "MAC", optional=True),
        Column("assigned_to", "Assigned To", optional=True,
              help="Workspace name, or the person id when the device is user-owned."),
    ],
    fetch=fetch_devices,
    actions=[
        Action(
            id="delete",
            label="Delete",
            handler=act_delete_device,
            scope_mode="selection",
            style="danger",
            confirm="Delete these devices?",
            removes_row=True,
        ),
    ],
))


# -- webex.numbers ------------------------------------------------------------


def fetch_numbers(ctx: Context) -> List[Item]:
    wx = ctx.client
    result = wx.list_numbers()
    if not result.get("success"):
        ctx.log(f"Failed to list numbers: {result.get('error')}")
        return []
    name_by_id, _ = _location_maps(ctx)
    items: List[Item] = []
    for num in result.get("response") or []:
        owner = num.get("owner") or {}
        location = num.get("location") or {}
        phone_number = num.get("phoneNumber", "")
        first, last = owner.get("firstName", ""), owner.get("lastName", "")
        owner_name = f"{first} {last}".strip() or owner.get("name", "")
        items.append(Item(
            # The E.164 number is the key (unique per org) and so is not
            # repeated below as a "number" column; see the module docstring.
            key=phone_number or num.get("extension", ""),
            fields={
                "extension": num.get("extension", ""),
                "state": num.get("state", ""),
                "location": location.get("name") or name_by_id.get(location.get("id", ""), ""),
                "location_id": location.get("id", ""),
                "owner_type": owner.get("type", ""),
                "owner_name": owner_name,
                "main_number": bool(num.get("mainNumber", False)),
            },
        ))
    return items


def act_add_numbers(ctx: Context, item):
    wx = ctx.client
    p = ctx.params
    location_name = (p.get("location") or "").strip()
    raw_numbers = p.get("numbers") or ""
    number_type = p.get("number_type") or "DID"
    state = p.get("state") or "ACTIVE"
    numbers = [n.strip() for n in raw_numbers.replace(",", "\n").splitlines() if n.strip()]
    if not location_name or not numbers:
        return False, "Location and at least one number are required"
    _, id_by_name = _location_maps(ctx)
    location_id = id_by_name.get(location_name)
    if not location_id:
        return False, f"Unknown location {location_name!r}"
    formatted = [n if n.startswith("+") else f"+{n}" for n in numbers]
    result = wx.add_numbers(location_id, formatted, number_type=number_type,
                            number_usage_type="NONE", state=state)
    if not result.get("success"):
        return False, result.get("error") or "Failed to add numbers"
    return True, f"Added {len(formatted)} number(s) to {location_name}"


def act_delete_number(ctx: Context, item: dict):
    fields = item["fields"]
    location_id = fields.get("location_id")
    number = item.get("key") or ""
    if not location_id or not number:
        return False, "Missing location or number"
    result = ctx.client.delete_numbers(location_id, [number])
    if not result.get("success"):
        return False, result.get("error") or "Failed to remove number"
    return True, "Number removed"


register(ResourceSpec(
    id="webex.numbers",
    service="WEBEX",
    label="PSTN Numbers",
    key_label="Number",
    description="PSTN numbers assigned in the org.",
    columns=[
        Column("extension", "Extension", optional=True),
        Column("state", "State", kind="badge", tone_map={"ACTIVE": "ok", "INACTIVE": "muted"}),
        Column("location", "Location"),
        Column("owner_type", "Owner Type", optional=True),
        Column("owner_name", "Owner", optional=True),
        Column("main_number", "Main Number", kind="bool"),
    ],
    fetch=fetch_numbers,
    actions=[
        Action(
            id="add",
            label="Add Numbers",
            handler=act_add_numbers,
            scope_mode="form",
            style="primary",
            fields=[
                Field("location", "Location", kind="select", required=True,
                     options_from="webex.locations:name"),
                Field("numbers", "Numbers", kind="textarea", required=True,
                     help="One per line or comma separated; 10 or 11 digit US numbers, "
                         "no + needed."),
                Field("number_type", "Number Type", kind="select",
                     options=["DID", "TOLLFREE"], default="DID"),
                Field("state", "State", kind="select",
                     options=["ACTIVE", "INACTIVE"], default="ACTIVE"),
            ],
            help="Based on AddNumbersToLocation.py.",
        ),
        Action(
            id="delete",
            label="Delete",
            handler=act_delete_number,
            scope_mode="selection",
            style="danger",
            confirm="Remove these numbers from their locations?",
            removes_row=True,
            help="Based on ModifyNumbers.py.",
        ),
    ],
))


# -- webex.call_queues and webex.hunt_groups ----------------------------------
#
# Both are addressed as /telephony/config/locations/{locationId}/<kind>/{id},
# so both need location_id carried alongside the object id in fields. They
# share the same create/set_agents/delete shape, built with small
# kind-specific closures below rather than duplicating the whole spec twice.


def _fetch_location_scoped(ctx: Context, list_method_name: str, response_key: str) -> List[Item]:
    wx = ctx.client
    result = getattr(wx, list_method_name)()
    if not result.get("success"):
        ctx.log(f"Failed to list {response_key}: {result.get('error')}")
        return []
    name_by_id, _ = _location_maps(ctx)
    items: List[Item] = []
    for entry in result.get("response") or []:
        location_id = entry.get("locationId", "")
        location = entry.get("locationName") or name_by_id.get(location_id, "")
        items.append(Item(
            key=entry.get("id", ""),
            fields={
                "name": entry.get("name", ""),
                "location": location,
                "location_id": location_id,
                "extension": entry.get("extension", ""),
                "phone_number": entry.get("phoneNumber", ""),
                "agent_count": entry.get("agentCount", entry.get("numberOfAgents", 0)) or 0,
                "enabled": bool(entry.get("enabled", True)),
            },
        ))
    return items


def fetch_call_queues(ctx: Context) -> List[Item]:
    return _fetch_location_scoped(ctx, "list_call_queues", "queues")


def fetch_hunt_groups(ctx: Context) -> List[Item]:
    return _fetch_location_scoped(ctx, "list_hunt_groups", "hunt groups")


def _build_queue_or_group_payload(ctx: Context) -> dict:
    p = ctx.params
    name = (p.get("name") or "").strip()
    agents = _resolve_agents(ctx, p.get("agents") or "")
    policy = (p.get("policy") or "CIRCULAR").strip()
    destination = (p.get("destination") or "").strip()
    call_policies = {"policy": policy}
    if destination:
        call_policies["noAnswer"] = {"enabled": True, "destination": destination}
        call_policies["businessContinuity"] = {"enabled": True, "destination": destination}
    return _strip_blanks({
        "name": name,
        "phoneNumber": (p.get("phone_number") or "").strip(),
        "extension": (p.get("extension") or "").strip(),
        "callPolicies": call_policies,
        "agents": agents,
        "enabled": True,
    })


def act_create_call_queue(ctx: Context, item):
    p = ctx.params
    name = (p.get("name") or "").strip()
    location_name = (p.get("location") or "").strip()
    if not name or not location_name:
        return False, "Name and location are required"
    _, id_by_name = _location_maps(ctx)
    location_id = id_by_name.get(location_name)
    if not location_id:
        return False, f"Unknown location {location_name!r}"
    payload = _build_queue_or_group_payload(ctx)
    result = ctx.client.create_call_queue(location_id, payload)
    if not result.get("success"):
        return False, result.get("error") or "Failed to create call queue"
    return True, f"Call queue {name!r} created"


def act_create_hunt_group(ctx: Context, item):
    p = ctx.params
    name = (p.get("name") or "").strip()
    location_name = (p.get("location") or "").strip()
    if not name or not location_name:
        return False, "Name and location are required"
    _, id_by_name = _location_maps(ctx)
    location_id = id_by_name.get(location_name)
    if not location_id:
        return False, f"Unknown location {location_name!r}"
    payload = _build_queue_or_group_payload(ctx)
    result = ctx.client.create_hunt_group(location_id, payload)
    if not result.get("success"):
        return False, result.get("error") or "Failed to create hunt group"
    return True, f"Hunt group {name!r} created"


def _set_agents(ctx: Context, item: dict, get_method_name: str, update_method_name: str):
    wx = ctx.client
    fields = item["fields"]
    location_id = fields.get("location_id")
    object_id = item.get("key")
    if not location_id or not object_id:
        return False, "Missing location or id"
    new_agents = _resolve_agents(ctx, ctx.params.get("agents") or "")
    mode = (ctx.params.get("mode") or "replace").lower()
    if mode == "append":
        existing = getattr(wx, get_method_name)(location_id, object_id)
        if not existing.get("success"):
            return False, existing.get("error") or "Failed to read current agents"
        current = list((existing.get("response") or {}).get("agents") or [])
        seen = {a.get("id") for a in current if a.get("id")}
        for agent in new_agents:
            if agent["id"] not in seen:
                current.append(agent)
                seen.add(agent["id"])
        new_agents = current
    result = getattr(wx, update_method_name)(location_id, object_id, {"agents": new_agents})
    if not result.get("success"):
        return False, result.get("error") or "Failed to update agents"
    return True, f"Agents updated ({len(new_agents)} total)"


def act_set_queue_agents(ctx: Context, item: dict):
    return _set_agents(ctx, item, "get_call_queue", "update_call_queue")


def act_set_hunt_group_agents(ctx: Context, item: dict):
    return _set_agents(ctx, item, "get_hunt_group", "update_hunt_group")


def act_delete_call_queue(ctx: Context, item: dict):
    fields = item["fields"]
    location_id, queue_id = fields.get("location_id"), item.get("key")
    if not location_id or not queue_id:
        return False, "Missing location or queue id"
    result = ctx.client.delete_call_queue(location_id, queue_id)
    if not result.get("success"):
        return False, result.get("error") or "Failed to delete call queue"
    return True, "Call queue deleted"


def act_delete_hunt_group(ctx: Context, item: dict):
    fields = item["fields"]
    location_id, group_id = fields.get("location_id"), item.get("key")
    if not location_id or not group_id:
        return False, "Missing location or hunt group id"
    result = ctx.client.delete_hunt_group(location_id, group_id)
    if not result.get("success"):
        return False, result.get("error") or "Failed to delete hunt group"
    return True, "Hunt group deleted"


_AGENT_FIELDS = [
    Field("agents", "Agents", kind="textarea", required=True,
         help="Emails (users) or extensions/DNs (virtual lines), one per line or "
             "comma separated."),
]

_QUEUE_GROUP_CREATE_FIELDS = [
    Field("name", "Name", kind="text", required=True),
    Field("location", "Location", kind="select", required=True,
         options_from="webex.locations:name"),
    Field("phone_number", "Phone Number"),
    Field("extension", "Extension"),
    Field("policy", "Routing Policy", kind="select",
         options=["CIRCULAR", "UNIFORM", "SIMULTANEOUS", "WEIGHTED", "SKILL_BASED"],
         default="CIRCULAR"),
    Field("destination", "No-Answer Forward Destination"),
] + _AGENT_FIELDS

_SET_AGENTS_FIELDS = [
    Field("mode", "Mode", kind="select", options=["replace", "append"], default="replace"),
] + _AGENT_FIELDS

register(ResourceSpec(
    id="webex.call_queues",
    service="WEBEX",
    label="Call Queues",
    key_label="ID",
    description="Call queues, per calling location.",
    columns=[
        Column("name", "Name"),
        Column("location", "Location"),
        Column("extension", "Extension", optional=True),
        Column("phone_number", "Phone Number", optional=True),
        Column("agent_count", "Agents", kind="number"),
        Column("enabled", "Enabled", kind="bool"),
    ],
    fetch=fetch_call_queues,
    actions=[
        Action(
            id="create",
            label="Create Call Queue",
            handler=act_create_call_queue,
            scope_mode="form",
            style="primary",
            fields=_QUEUE_GROUP_CREATE_FIELDS,
            help="Based on CreateCallQueue.py.",
        ),
        Action(
            id="set_agents",
            label="Set Agents",
            handler=act_set_queue_agents,
            scope_mode="selection",
            style="secondary",
            fields=_SET_AGENTS_FIELDS,
            help="Based on UpdateCallQueueAgents.py.",
        ),
        Action(
            id="delete",
            label="Delete",
            handler=act_delete_call_queue,
            scope_mode="selection",
            style="danger",
            confirm="Delete these call queues?",
            removes_row=True,
        ),
    ],
))

register(ResourceSpec(
    id="webex.hunt_groups",
    service="WEBEX",
    label="Hunt Groups",
    key_label="ID",
    description="Hunt groups, per calling location.",
    columns=[
        Column("name", "Name"),
        Column("location", "Location"),
        Column("extension", "Extension", optional=True),
        Column("phone_number", "Phone Number", optional=True),
        Column("agent_count", "Agents", kind="number"),
        Column("enabled", "Enabled", kind="bool"),
    ],
    fetch=fetch_hunt_groups,
    actions=[
        Action(
            id="create",
            label="Create Hunt Group",
            handler=act_create_hunt_group,
            scope_mode="form",
            style="primary",
            fields=_QUEUE_GROUP_CREATE_FIELDS,
            help="Based on CreateHuntGroup.py.",
        ),
        Action(
            id="set_agents",
            label="Set Agents",
            handler=act_set_hunt_group_agents,
            scope_mode="selection",
            style="secondary",
            fields=_SET_AGENTS_FIELDS,
            help="Based on UpdateHuntGroupAgents.py.",
        ),
        Action(
            id="delete",
            label="Delete",
            handler=act_delete_hunt_group,
            scope_mode="selection",
            style="danger",
            confirm="Delete these hunt groups?",
            removes_row=True,
        ),
    ],
))


# -- webex.groups -------------------------------------------------------------


def fetch_groups(ctx: Context) -> List[Item]:
    wx = ctx.client
    result = wx.list_groups()
    if not result.get("success"):
        ctx.log(f"Failed to list groups: {result.get('error')}")
        return []
    items: List[Item] = []
    for grp in result.get("response") or []:
        name = grp.get("displayName", "") or grp.get("id", "")
        items.append(Item(
            key=name,
            fields={
                "id": grp.get("id", ""),
                "member_count": grp.get("memberCount", 0) or 0,
            },
        ))
    return items


register(ResourceSpec(
    id="webex.groups",
    service="WEBEX",
    label="User Groups",
    key_label="Name",
    description="Org user groups (read-only; used to add users to a group from "
               "the Users page).",
    columns=[
        Column("member_count", "Members", kind="number"),
    ],
    fetch=fetch_groups,
))
