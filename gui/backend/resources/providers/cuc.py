#!/usr/bin/env python3

"""
CUC (Cisco Unity Connection) resources for the web GUI.

Registers two ResourceSpecs, service "CUC":

    cuc.call_handlers  Call Handlers - every call handler (system, subscriber
        and non-subscriber), with its menu entries and what refers back to it.
    cuc.users          Mailbox Users - subscriber accounts with mailbox usage
        (message count, size, mount state).

Key choice: both resources use the CUC ObjectId as Item.key. DisplayName
(call handlers) and Alias (users) are usually unique within a cluster, but
ObjectId is *guaranteed* unique and is what cucAPI's delete methods take, so
it is the safer choice for a cache primary key. The human-readable name still
appears as an ordinary column so the table reads naturally; only the key
itself (shown via key_label) is left off the column list, per the resource
contract in gui/backend/resources/types.py.

Dependency scanning for call handlers walks every OTHER handler's menu
entries looking for one that targets the handler in question - the same
graph cuc/list_NonSubscriber_CallHandlers_WithMenuEntries.py builds for
build_call_trees.py. Doing that walk once per row would be one CUC call per
handler per handler (O(n^2)), so the reverse index is built once and cached
on the Context instance: the registry hands the same Context to every deps()
call within one sync or scan_deps batch (see gui/backend/resources/registry.py).
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from gui.backend.resources.registry import register
from gui.backend.resources.types import (
    Action, Column, Context, Dependency, Field, Item, ResourceSpec,
)

ROOT = Path(__file__).resolve().parents[4]
CUC_DIR = ROOT / "cuc"
if str(CUC_DIR) not in sys.path:
    sys.path.insert(0, str(CUC_DIR))

# Built-in system handlers hidden from the table, same set every CUC list/delete
# script in cuc/ skips (they are not real customer-managed objects).
SKIP_HANDLERS = {
    'Opening Greeting',
    'Operator',
    'Goodbye',
    'undeliverablemessagesmailbox',
    'operator',
}

_MENU_INDEX_ATTR = "_cuc_call_handler_menu_index"


def _key_rank(value: str):
    """Sort key for a touchtone key: 0-9, then *, then #, then anything else."""
    order = {str(i): i for i in range(10)}
    order.update({"*": 10, "#": 11})
    return order.get(value, 99), value


def _owner_type(fields: dict) -> str:
    """Classify a call handler's recipient, mirroring classify_call_handlers()
    in cuc/list_NonSubscriber_CallHandlers_WithMenuEntries.py."""
    if fields.get('RecipientSubscriberObjectId'):
        return 'Subscriber'
    if fields.get('RecipientDistributionListObjectId'):
        return 'Distribution List'
    if fields.get('RecipientContactObjectId'):
        return 'Contact'
    return 'System/Application'


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


# -- cuc.call_handlers ------------------------------------------------------

def fetch_call_handlers(ctx: Context) -> List[Item]:
    """Every call handler, with its menu entries. See module docstring for the
    exclude_subscribers filter and the key choice."""
    cuc = ctx.client
    exclude_subscribers = _truthy(ctx.params.get('exclude_subscribers', ''))

    result = cuc.list_call_handlers()
    if not result['success']:
        raise RuntimeError(result.get('error') or 'Failed to list call handlers')
    raw_handlers = result['response']

    candidates = []
    for handler in raw_handlers:
        object_id = handler.get('ObjectId', '')
        display_name = handler.get('DisplayName', '')
        if not object_id or display_name in SKIP_HANDLERS:
            continue
        if exclude_subscribers and handler.get('RecipientSubscriberObjectId'):
            continue
        candidates.append(handler)

    items: List[Item] = []
    total = len(candidates)
    for index, handler in enumerate(candidates, start=1):
        if ctx.cancelled():
            break
        object_id = handler.get('ObjectId', '')
        display_name = handler.get('DisplayName', '')
        ctx.progress(index, total, f"Call handler menu entries: {display_name}")

        menu_labels: List[str] = []
        menu_result = cuc.get_menu_entries(object_id)
        if menu_result['success']:
            entries = sorted(menu_result['response'],
                              key=lambda e: _key_rank(e.get('TouchtoneKey', '')))
            for entry in entries:
                key = entry.get('TouchtoneKey', '') or '?'
                destination = (entry.get('DisplayName') or entry.get('TransferNumber')
                              or entry.get('TargetConversation')
                              or entry.get('TargetHandlerObjectId') or '')
                if destination:
                    menu_labels.append(f"{key}: {destination}")

        items.append(Item(
            key=object_id,
            fields={
                'display_name': display_name,
                'extension': handler.get('DtmfAccessId', ''),
                'owner_type': _owner_type(handler),
                'menu_entries': menu_labels,
                # not shown as a column (it duplicates the key); kept for deps()
                'object_id': object_id,
            },
        ))
    return items


def _reverse_menu_index(ctx: Context) -> Dict[str, List[Dependency]]:
    """Return {target ObjectId: [Dependency, ...]} built from every handler's
    menu entries, cached on ctx for the life of one sync/scan_deps batch."""
    cached = getattr(ctx, _MENU_INDEX_ATTR, None)
    if cached is not None:
        return cached

    index: Dict[str, List[Dependency]] = {}
    cuc = ctx.client
    handlers_result = cuc.list_call_handlers()
    if handlers_result['success']:
        handlers = handlers_result['response']
        name_by_id = {h.get('ObjectId', ''): h.get('DisplayName', '')
                     for h in handlers if h.get('ObjectId')}
        for handler in handlers:
            source_id = handler.get('ObjectId', '')
            if not source_id:
                continue
            menu_result = cuc.get_menu_entries(source_id)
            if not menu_result['success']:
                continue
            for entry in menu_result['response']:
                target_id = entry.get('TargetHandlerObjectId', '')
                if not target_id:
                    continue
                key = entry.get('TouchtoneKey', '')
                index.setdefault(target_id, []).append(Dependency(
                    name=name_by_id.get(source_id, source_id) or source_id,
                    type='Menu Entry',
                    detail=f"key {key}" if key else 'menu entry',
                ))
    setattr(ctx, _MENU_INDEX_ATTR, index)
    return index


def call_handler_deps(ctx: Context, fields: dict) -> List[Dependency]:
    """Menu entries on OTHER handlers that transfer to this one."""
    object_id = fields.get('object_id', '')
    if not object_id:
        return []
    return _reverse_menu_index(ctx).get(object_id, [])


def action_delete_call_handler(ctx: Context, item: dict):
    object_id = item['key']
    display_name = item.get('fields', {}).get('display_name', object_id)
    result = ctx.client.delete_call_handler(object_id)
    if result['success']:
        return True, f"Deleted {display_name}"
    return False, result.get('error') or 'Delete failed'


def action_export_call_tree_workbook(ctx: Context, item):
    """Write the call-tree Excel workbook to _DATA/reports, reusing the tree
    walk and sheet formatting from cuc/build_call_trees.py (openpyxl is an
    optional dependency for this repo, so it is only imported here)."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return False, "openpyxl is required: pip install openpyxl"

    from build_call_trees import build_tree_rows, is_routable, write_sheet
    from openpyxl import Workbook

    cuc = ctx.client
    ctx.progress(0, None, "Fetching call handlers")
    result = cuc.list_call_handlers()
    if not result['success']:
        return False, result.get('error') or 'Failed to list call handlers'
    raw_handlers = result['response']

    handlers = []
    for handler in raw_handlers:
        display_name = handler.get('DisplayName', '')
        object_id = handler.get('ObjectId', '')
        if not object_id or display_name in SKIP_HANDLERS:
            continue
        if handler.get('RecipientSubscriberObjectId'):
            continue
        handlers.append({
            'displayName': display_name,
            'extension': handler.get('DtmfAccessId', ''),
            'objectId': object_id,
            'uri': handler.get('URI', ''),
        })
    handlers_by_id = {row['objectId']: row for row in handlers}

    menu_entries = []
    total = len(handlers)
    for index, handler in enumerate(handlers, start=1):
        if ctx.cancelled():
            return False, "Cancelled"
        ctx.progress(index, total, f"Menu entries: {handler['displayName']}")
        menu_result = cuc.get_menu_entries(handler['objectId'])
        if not menu_result['success']:
            continue
        for entry in menu_result['response']:
            target_id = entry.get('TargetHandlerObjectId', '')
            target_name = handlers_by_id.get(target_id, {}).get('displayName', '')
            if target_id:
                destination_type = 'Call Handler'
            elif entry.get('TransferNumber'):
                destination_type = 'Transfer'
            elif entry.get('TargetConversation'):
                destination_type = 'Conversation'
            else:
                destination_type = 'No configured destination'
            destination_name = (target_name or entry.get('DisplayName')
                                or entry.get('TransferNumber')
                                or entry.get('TargetConversation') or '')
            menu_entries.append({
                'sourceHandler': handler['displayName'],
                'sourceExtension': handler['extension'],
                'sourceObjectId': handler['objectId'],
                'touchToneKey': entry.get('TouchtoneKey', ''),
                'destinationType': destination_type,
                'destinationName': destination_name,
                'targetHandlerObjectId': target_id,
                'targetHandlerName': target_name,
                'transferNumber': entry.get('TransferNumber', ''),
                'targetConversation': entry.get('TargetConversation', ''),
                'transferDisplayName': entry.get('DisplayName', ''),
            })

    routable_entries = [row for row in menu_entries if is_routable(row)]
    edges_by_source: Dict[str, list] = {}
    targeted_ids = set()
    for row in routable_entries:
        edges_by_source.setdefault(row['sourceObjectId'], []).append(row)
        target_id = row.get('targetHandlerObjectId', '')
        if target_id:
            targeted_ids.add(target_id)

    source_ids = set(edges_by_source)
    root_ids = sorted(source_ids - targeted_ids,
                      key=lambda oid: handlers_by_id.get(oid, {}).get('displayName', oid).casefold())

    issues: list = []
    covered = set()
    tree_rows = []
    for root_id in root_ids:
        rows = build_tree_rows(root_id, handlers_by_id, edges_by_source, issues)
        tree_rows.extend(rows)
        covered.update(str(r.get('sourceObjectId', '')) for r in rows if r.get('sourceObjectId'))
    for source_id in sorted(source_ids - covered):
        tree_rows.extend(build_tree_rows(source_id, handlers_by_id, edges_by_source, issues))

    reports_dir = ROOT / '_DATA' / 'reports'
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    filename = f"call_trees-{ctx.scope}-{timestamp}.xlsx"
    output_path = reports_dir / filename

    workbook = Workbook()
    workbook.remove(workbook.active)

    ws_handlers = workbook.create_sheet('Call Handlers')
    write_sheet(ws_handlers, ['displayName', 'extension', 'objectId', 'uri'],
               handlers, 'CallHandlersTable')

    ws_tree = workbook.create_sheet('Call Trees')
    tree_headers = ['rootHandler', 'rootExtension', 'level', 'tree', 'path',
                    'sourceHandler', 'sourceObjectId', 'touchToneKey',
                    'destinationType', 'destinationName', 'transferNumber',
                    'targetHandlerObjectId', 'status']
    write_sheet(ws_tree, tree_headers, tree_rows, 'CallTreesTable')

    if issues:
        ws_issues = workbook.create_sheet('Issues')
        issue_headers = ['issueType', 'sourceHandler', 'sourceObjectId', 'touchToneKey',
                         'targetHandler', 'targetObjectId', 'details']
        write_sheet(ws_issues, issue_headers, issues, 'IssuesTable')

    workbook.save(output_path)
    return True, f"Wrote {filename} to _DATA/reports ({len(tree_rows)} tree rows, {len(issues)} issues)"


CALL_HANDLERS = ResourceSpec(
    id="cuc.call_handlers",
    service="CUC",
    label="Call Handlers",
    key_label="Object Id",
    description="Call handlers on the Unity Connection cluster, with their "
               "extension, owner, and menu entries.",
    columns=[
        Column("display_name", "Display Name"),
        Column("extension", "Extension"),
        Column("owner_type", "Owner / Type", kind="badge", tone_map={
            "Subscriber": "info", "Distribution List": "info",
            "Contact": "info", "System/Application": "muted",
        }),
        Column("menu_entries", "Menu Entries", kind="list", optional=True,
              help="Touchtone key -> destination"),
        Column("deps", "Referenced By", kind="deps"),
    ],
    fetch=fetch_call_handlers,
    deps=call_handler_deps,
    deps_label="Referenced By",
    filters=[
        Field(name="exclude_subscribers", label="Exclude subscriber handlers",
             kind="bool", default="false",
             help="Drop the per-user subscriber (mailbox) handlers, "
                  "matching list_NonSubscriber_CallHandlers_WithMenuEntries.py"),
    ],
    actions=[
        Action(id="delete", label="Delete", handler=action_delete_call_handler,
              scope_mode="selection", style="danger",
              confirm="Delete the selected call handlers? This cannot be undone.",
              block_when_deps=True, removes_row=True),
        Action(id="export_workbook", label="Export Call Tree Workbook",
              handler=action_export_call_tree_workbook, scope_mode="none",
              resync_after=False,
              help="Writes the call-tree Excel workbook into _DATA/reports."),
    ],
)


# -- cuc.users ----------------------------------------------------------------

def fetch_users(ctx: Context) -> List[Item]:
    """Mailbox users with alias, extension and mailbox usage.

    One API call per user is needed for mailbox usage (no bulk endpoint), so
    this honours ctx.progress()/ctx.cancelled() and spec.sync_note warns that
    a full sync of a large cluster is slow.
    """
    cuc = ctx.client
    search = str(ctx.params.get('search', '')).strip().lower()

    result = cuc.list_users()
    if not result['success']:
        raise RuntimeError(result.get('error') or 'Failed to list users')
    raw_users = result['response']

    if search:
        raw_users = [u for u in raw_users
                    if search in (u.get('Alias', '') or '').lower()
                    or search in (u.get('DtmfAccessId', '') or '').lower()]

    items: List[Item] = []
    total = len(raw_users)
    for index, user in enumerate(raw_users, start=1):
        if ctx.cancelled():
            break
        object_id = user.get('ObjectId', '')
        if not object_id:
            continue
        alias = user.get('Alias', '')
        user_uri = user.get('URI', '')
        ctx.progress(index, total, f"Mailbox usage: {alias or object_id}")

        message_count = 0
        mailbox_bytes = 0
        mailbox_state = ''
        if user_uri:
            mailbox_result = cuc.get_mailbox_attributes(user_uri)
            if mailbox_result['success']:
                mailbox = mailbox_result['response']
                try:
                    mailbox_bytes = int(mailbox.get('ByteSize') or 0)
                except ValueError:
                    mailbox_bytes = 0
                try:
                    message_count = int(mailbox.get('NumMessages') or 0)
                except ValueError:
                    message_count = 0
                mounted = str(mailbox.get('IsMailboxMounted',
                                          mailbox.get('Mounted', ''))).strip().lower()
                if mounted == 'true':
                    mailbox_state = 'Mounted'
                elif mounted == 'false':
                    mailbox_state = 'Not Mounted'
            else:
                mailbox_state = 'Error'

        items.append(Item(
            key=object_id,
            fields={
                'alias': alias,
                'display_name': user.get('DisplayName', ''),
                'extension': user.get('DtmfAccessId', ''),
                'message_count': message_count,
                'mailbox_bytes': mailbox_bytes,
                'mailbox_state': mailbox_state,
            },
        ))
    return items


def action_delete_user(ctx: Context, item: dict):
    """Delete the user account (there is no way to remove only the mailbox
    and keep the user, per cuc/cleanup_emptyMailboxes.py)."""
    object_id = item['key']
    alias = item.get('fields', {}).get('alias', object_id)
    result = ctx.client.delete_user_by_id(object_id)
    if result['success']:
        return True, f"Deleted user account {alias}"
    return False, result.get('error') or 'Delete failed'


def action_export_usage_csv(ctx: Context, item):
    """Write the mailbox usage CSV into _DATA, from the cached (synced) rows."""
    from gui.backend import db

    rows = db.get_items('cuc.users', scopes=[ctx.scope])
    if not rows:
        return False, "No cached mailbox users for this scope; sync first"

    data_dir = ROOT / '_DATA'
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    filename = f"mailbox_usage-{ctx.scope}-{timestamp}.csv"
    output_path = data_dir / filename

    with output_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['dtmfAccessID', 'alias', 'displayName', 'mailboxSizeMB',
                         'messageCount', 'mailboxState'])
        for row in rows:
            fields = row.get('fields', {})
            size_mb = round((fields.get('mailbox_bytes') or 0) / (1024 * 1024), 2)
            writer.writerow([
                fields.get('extension', ''), fields.get('alias', ''),
                fields.get('display_name', ''), size_mb,
                fields.get('message_count', 0), fields.get('mailbox_state', ''),
            ])

    return True, f"Wrote {filename} to _DATA ({len(rows)} users)"


USERS = ResourceSpec(
    id="cuc.users",
    service="CUC",
    label="Mailbox Users",
    key_label="Object Id",
    description="Mailbox users with alias, extension and mailbox usage "
               "(message count, size, mount state).",
    columns=[
        Column("alias", "Alias"),
        Column("display_name", "Display Name"),
        Column("extension", "Extension"),
        Column("message_count", "Messages", kind="number"),
        Column("mailbox_bytes", "Mailbox Size", kind="bytes"),
        Column("mailbox_state", "Mailbox State", kind="badge", tone_map={
            "Mounted": "ok", "Not Mounted": "warn", "Error": "danger",
        }),
    ],
    fetch=fetch_users,
    filters=[
        Field(name="search", label="Search (alias or extension)", kind="text",
             placeholder="e.g. jsmith or 2001"),
    ],
    sync_note="Mailbox usage is one API call per user; syncing a large "
             "cluster can take several minutes.",
    actions=[
        Action(id="delete", label="Delete", handler=action_delete_user,
              scope_mode="selection", style="danger",
              confirm="Delete the selected user accounts? This removes the "
                      "mailbox and cannot be undone.",
              removes_row=True),
        Action(id="export", label="Export Usage CSV", handler=action_export_usage_csv,
              scope_mode="none", resync_after=False,
              help="Writes the mailbox usage CSV into _DATA."),
    ],
)


register(CALL_HANDLERS)
register(USERS)
