#!/usr/bin/env python3

"""
Which resource panels each script's page shows in the web GUI.

Every script in the launcher keeps its page, but the page's content is now
the rich resource UI instead of a scrolling CLI log: one or more resource
panels (sync button, table with checkboxes and a dependencies column,
select all / unselect all, action buttons) chosen per script here.

A rel that is absent from PAGES falls back to the prompt-driven script
runner, which still works for every script and is also available on every
page under "Run the script instead" - the escape hatch for anything the
resource layer does not model yet.

`resources` is a list of resource ids from
gui/backend/resources/registry.py. The first one is the page's primary
panel. `hide_actions` trims a shared resource's button row down to what
the script the page replaces was actually for: the Delete Softkey
Templates page shows delete, the List page does not, even though both read
cucm.softkey_templates.

GET /api/health reports any id here that no provider registers, so a typo
shows up as a startup warning rather than an empty page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


@dataclass
class PageSpec:
    """The rich-GUI layout for one script's page."""

    resources: Sequence[str]
    intro: str = ""
    #: action ids to hide on this page (they stay available on other pages)
    hide_actions: Sequence[str] = ()
    #: tick "include dependencies" by default when the page opens
    deps_default: bool = False
    #: pre-set filter values for the primary panel
    filters: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"resources": list(self.resources), "intro": self.intro,
                "hide_actions": list(self.hide_actions),
                "deps_default": self.deps_default, "filters": self.filters}


PAGES: Dict[str, PageSpec] = {

    # -- CUCM -------------------------------------------------------------

    "cucm/list_softkey_templates.py": PageSpec(
        resources=["cucm.softkey_templates"],
        intro="Sync pulls every custom softkey template and, with dependencies "
              "included, what uses each one. Templates with no dependencies are "
              "the ones that are safe to remove.",
        hide_actions=["delete"],
        deps_default=True,
    ),
    "cucm/delete_softkey_templates.py": PageSpec(
        resources=["cucm.softkey_templates"],
        intro="Tick the templates to remove and press Delete. Templates that "
              "still have dependencies are refused, and system templates are "
              "greyed out.",
        deps_default=True,
    ),
    "cucm/remediate_softkey_templates.py": PageSpec(
        resources=["cucm.softkey_templates"],
        intro="Dependency-driven cleanup: sync with dependencies, then delete "
              "the unused templates in one pass.",
        deps_default=True,
    ),
    "cucm/clean_unused_phone_button_templates.py": PageSpec(
        resources=["cucm.phone_button_templates"],
        intro="Phone button templates and the devices, profiles and phone "
              "types that reference them. Unreferenced templates can be "
              "deleted from here.",
        deps_default=True,
    ),
    "cucm/remediate_partitions.py": PageSpec(
        resources=["cucm.route_partitions"],
        intro="Route partitions with their dependency counts. Empty partitions "
              "can be deleted directly.",
        deps_default=True,
    ),
    "cucm/remediate_duplicatish-RPs.py": PageSpec(
        resources=["cucm.route_partitions"],
        intro="Look for partitions that differ only in punctuation or case, "
              "then delete the unused duplicates.",
        deps_default=True,
    ),
    "cucm/remediate_callingSearchSpaces.py": PageSpec(
        resources=["cucm.calling_search_spaces"],
        intro="Calling search spaces, their member partitions and what "
              "references them.",
        deps_default=True,
    ),
    "cucm/remediate_locations.py": PageSpec(
        resources=["cucm.locations"],
        intro="Locations with their dependency counts. Locations nothing "
              "references can be deleted from here.",
        deps_default=True,
    ),
    "cucm/remediate_regions.py": PageSpec(
        resources=["cucm.regions"],
        intro="Regions with their dependency counts, and the device pools "
              "that sit in each one.",
        deps_default=True,
    ),
    "cucm/create_region_update_device_pools.py": PageSpec(
        resources=["cucm.regions", "cucm.device_pools"],
        intro="Add a region, then point the chosen device pools at it.",
    ),
    "cucm/count_phones_by_device_pool.py": PageSpec(
        resources=["cucm.device_pools"],
        intro="Registered phone counts per device pool, straight from the "
              "publisher.",
    ),
    "cucm/create_audio_codec_preference_list.py": PageSpec(
        resources=["cucm.audio_codec_preference_lists"],
        intro="Audio codec preference lists, and a form to add one.",
    ),
    "cucm/add_advertisted_pattern.py": PageSpec(
        resources=["cucm.advertised_patterns"],
        intro="Hosted DN and PSTN advertised patterns. Add one with the form, "
              "or upload a CSV on the script tab for a bulk load.",
        hide_actions=["delete"],
    ),
    "cucm/remove_advertisted_pattern.py": PageSpec(
        resources=["cucm.advertised_patterns"],
        intro="Tick the advertised patterns to withdraw and press Delete. "
              "A pattern that needs a leading + is retried automatically.",
        hide_actions=["add"],
    ),
    "cucm/export_advertised_patterns.py": PageSpec(
        resources=["cucm.advertised_patterns"],
        intro="Sync, then Export CSV to write the current patterns into _DATA.",
        hide_actions=["add", "delete"],
    ),
    "cucm/compare_advP-RP.py": PageSpec(
        resources=["cucm.advertised_patterns", "cucm.route_patterns"],
        intro="Sync both panels, then compare: advertised patterns with no "
              "matching route pattern are the gaps.",
        hide_actions=["add", "delete"],
    ),
    "cucm/remedy-RP-oneoff.py": PageSpec(
        resources=["cucm.route_patterns"],
        intro="Route patterns, filtered to the ones missing a non-dotted "
              "format.",
    ),
    "cucm/update_PhoneLoad.py": PageSpec(
        resources=["cucm.phones"],
        intro="Filter to the phones you want, tick them, then set the "
              "firmware load and optionally reset.",
    ),
    "cucm/update_LoadServer.py": PageSpec(
        resources=["cucm.phones"],
        intro="Filter to the phones you want, tick them, then set the load "
              "server.",
    ),
    "cucm/lookup_device_type.py": PageSpec(
        resources=["cucm.phones"],
        intro="Phones with their resolved device type and model, so a phone "
              "model can be traced back to its AXL product id.",
    ),
    "cucm/em_bulk_login.py": PageSpec(
        resources=["cucm.phones"],
        intro="Extension Mobility bulk login runs from a CSV on the script "
              "tab; the phone list here is for checking device names first.",
    ),
    "cucm/move_DN_partition.py": PageSpec(
        resources=["cucm.lines"],
        intro="Find the directory numbers, tick them, then move them to "
              "another route partition.",
    ),
    "cucm/remove_DN_EnterpriseAlternateNumber.py": PageSpec(
        resources=["cucm.lines"],
        intro="Find the directory numbers, tick them, then clear their "
              "enterprise alternate number.",
    ),
    "cucm/remove_DN_EntAltNum-E164AltNum.py": PageSpec(
        resources=["cucm.lines"],
        intro="Find the directory numbers, tick them, then clear both the "
              "enterprise and the +E.164 alternate number.",
    ),
    "cucm/set_user_pin.py": PageSpec(
        resources=["cucm.users"],
        intro="Find the end users, tick them, then set a PIN. The PIN is "
              "typed into a password field and is never echoed or logged.",
    ),

    # -- CUC --------------------------------------------------------------

    "cuc/list_CallHandlers.py": PageSpec(
        resources=["cuc.call_handlers"],
        intro="Call handlers on the Unity Connection cluster, with their "
                "extension, owner and menu entries.",
        hide_actions=["delete"],
    ),
    "cuc/list_NonSubscriber_CallHandlers_WithMenuEntries.py": PageSpec(
        resources=["cuc.call_handlers"],
        intro="Call handlers excluding subscriber (user) handlers, showing "
              "which keys are mapped on each.",
        hide_actions=["delete"],
        filters={"exclude_subscribers": "true"},
    ),
    "cuc/delete_CallHandlers.py": PageSpec(
        resources=["cuc.call_handlers"],
        intro="Tick the call handlers to delete. Handlers referenced by a "
              "menu entry elsewhere are flagged in the dependencies column.",
        deps_default=True,
    ),
    "cuc/build_call_trees.py": PageSpec(
        resources=["cuc.call_handlers"],
        intro="Sync the handlers, then Export Call Tree Workbook to write the "
              "Excel version into _DATA/reports.",
        hide_actions=["delete"],
    ),
    "cuc/check_userMailbox.py": PageSpec(
        resources=["cuc.users"],
        intro="Mailbox users with their extension, alias and mailbox state.",
        hide_actions=["delete"],
    ),
    "cuc/check_userMailboxUsage.py": PageSpec(
        resources=["cuc.users"],
        intro="Mailbox users with message counts and mailbox size. Export CSV "
              "writes the usage report into _DATA.",
        hide_actions=["delete"],
    ),
    "cuc/cleanup_emptyMailboxes.py": PageSpec(
        resources=["cuc.users"],
        intro="Sync, sort by message count, tick the empty mailboxes and "
              "delete them.",
    ),

    # -- CUBE -------------------------------------------------------------

    "cube/check_router_mem_status.py": PageSpec(
        resources=["cube.memory"],
        intro="Memory and CPU headroom per router. Sync runs the show "
              "commands over SSH; rows over the threshold are flagged.",
    ),
    "cube/compare_router_config.py": PageSpec(
        resources=["cube.config_sections"],
        intro="Running-config sections per router, compared against the "
              "template in .var. Differences are listed per section.",
    ),

    # -- Webex ------------------------------------------------------------

    "webex/AddNumbersToLocation.py": PageSpec(
        resources=["webex.numbers", "webex.locations"],
        intro="PSTN numbers in the org. Add numbers to a location with the "
              "form, or tick numbers to remove them.",
    ),
    "webex/ModifyNumbers.py": PageSpec(
        resources=["webex.numbers"],
        intro="PSTN numbers with their state, location and owner.",
    ),
    "webex/DisableRedSkyOnLocations.py": PageSpec(
        resources=["webex.locations"],
        intro="Calling locations with their emergency-calling provider. Tick "
              "locations to turn RedSky routing off.",
    ),
    "webex/BulkDeleteUsers.py": PageSpec(
        resources=["webex.people"],
        intro="Find the users, tick them, then delete. Deleting a user in "
              "Control Hub cannot be undone.",
        deps_default=False,
    ),
    "webex/ResetUserPin.py": PageSpec(
        resources=["webex.people"],
        intro="Find the users, tick them, then set a voicemail PIN.",
        hide_actions=["delete"],
    ),
    "webex/CallFowardAll.py": PageSpec(
        resources=["webex.people"],
        intro="Find the users, tick them, then set Call Forward All to a "
              "destination.",
        hide_actions=["delete"],
    ),
    "webex/CallFowardAll-Remove.py": PageSpec(
        resources=["webex.people"],
        intro="Find the users, tick them, then turn Call Forward All off.",
        hide_actions=["delete"],
    ),
    "webex/CreateWorkspace.py": PageSpec(
        resources=["webex.workspaces"],
        intro="Workspaces in the org, and a form to create one.",
    ),
    "webex/AddDevicesWorkspaces.py": PageSpec(
        resources=["webex.workspaces", "webex.devices"],
        intro="Tick workspaces to generate device activation codes; the "
              "devices panel shows what is already registered.",
    ),
    "webex/CreateCallQueue.py": PageSpec(
        resources=["webex.call_queues"],
        intro="Call queues per location, and a form to create one.",
    ),
    "webex/UpdateCallQueueAgents.py": PageSpec(
        resources=["webex.call_queues"],
        intro="Tick the queues, then replace or extend their agent list.",
        hide_actions=["delete"],
    ),
    "webex/CreateHuntGroup.py": PageSpec(
        resources=["webex.hunt_groups"],
        intro="Hunt groups per location, and a form to create one.",
    ),
    "webex/UpdateHuntGroupAgents.py": PageSpec(
        resources=["webex.hunt_groups"],
        intro="Tick the hunt groups, then replace or extend their agent list.",
        hide_actions=["delete"],
    ),
    "webex/UpdateUserGroups.py": PageSpec(
        resources=["webex.groups", "webex.people"],
        intro="Org user groups with their member counts; tick users in the "
              "people panel to add them to a group.",
    ),
}


def for_rel(rel: str) -> Optional[PageSpec]:
    return PAGES.get(rel)


def referenced_resource_ids() -> List[str]:
    """Every resource id the page specs mention, de-duplicated."""
    seen: List[str] = []
    for spec in PAGES.values():
        for rid in spec.resources:
            if rid not in seen:
                seen.append(rid)
    return seen
