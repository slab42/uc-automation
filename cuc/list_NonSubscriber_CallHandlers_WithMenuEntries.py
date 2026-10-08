#!/usr/bin/env python3
# TITLE: Call Handlers List Non-Subscriber

"""
Export non-subscriber Cisco Unity Connection call handlers and their menu
entries to CSV.

Retrieves every call handler from CUC, classifies each as a subscriber
(user) handler or a non-subscriber (system/application) handler, skips a
fixed set of built-in handlers, and exports the remaining handlers plus
every MenuEntry attached to them. Menu entries that fail to retrieve for a
handler are written to a separate errors CSV.

Usage:
    python3 list_NonSubscriber_CallHandlers_WithMenuEntries.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use multiple clusters?: (y/n): choose 'y' to run against every CUC cluster
        in clusters.csv, or 'n' (default) to pick a single cluster.
    Call Handler CSV Output [_DATA/non_subscriber_callhandlers.csv]: path to
        save the call handler CSV.
    Menu Entry CSV Output [_DATA/menuentries.csv]: path to save the menu
        entry CSV. In multi-cluster mode, both outputs are suffixed with
        -<cluster_name> so clusters do not overwrite each other.

CSV Output Format - Call Handlers (displayName, extension, objectId, uri):
Sales Menu,2000,ca8cdbd5-9b1b-4893-9237-171d78b5c6a2,/vmrest/handlers/callhandlers/ca8cdbd5-9b1b-4893-9237-171d78b5c6a2

CSV Output Format - Menu Entries (sourceHandler, sourceExtension, sourceObjectId,
touchToneKey, locked, actionCode, destinationType, destinationName,
targetConversation, targetHandlerObjectId, targetHandlerName,
transferDisplayName, transferNumber, transferType, transferRings,
menuEntryObjectId, menuEntryUri):
Sales Menu,2000,ca8cdbd5-9b1b-4893-9237-171d78b5c6a2,1,FALSE,3,Call Handler,Support Queue,,f349f979-308b-4fad-b110-f58c132c2cae,Support Queue,,,,,menuentry-obj-1,/vmrest/.../menuentries/menuentry-obj-1

Output: _DATA/non_subscriber_callhandlers.csv, _DATA/menuentries.csv (defaults),
    plus <menu CSV stem>_errors.csv for any handler whose menu entries could
    not be retrieved. Feed the two main outputs into build_call_trees.py.
Logs: ../_logs/<timestamp>-list-nonsubscriber-call-handlers.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import csv
from datetime import datetime
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no, prompt_use_multiple
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from cucAPI import CUC

# Call Handlers to skip in export (built-in system handlers)
SKIP_HANDLERS = {
    'Opening Greeting',
    'Operator',
    'Goodbye',
    'undeliverablemessagesmailbox',
    'operator'
}


def clean(value):
    """Return a stripped string, or '' for None."""
    return str(value).strip() if value is not None else ''


def classify_call_handlers(cuc, logger):
    """
    Retrieve every Call Handler from CUC and split subscriber vs non-subscriber.

    Args:
        cuc: CUC API client instance
        logger: logger instance

    Returns:
        tuple: (non_subscriber_handlers, all_handlers_by_id)
            non_subscriber_handlers (list): dicts with displayName, extension,
                objectId, uri for handlers that are not a subscriber mailbox
                and not in SKIP_HANDLERS
            all_handlers_by_id (dict): objectId -> {'displayName', 'isSubscriber'}
                for every handler, including subscribers and skipped system
                handlers (used to resolve menu entry targets)
    """
    logger.info('Retrieving Call Handlers from %s', cuc.server)
    result = cuc.list_call_handlers()
    if not result.get('success'):
        logger.error('Failed to retrieve Call Handlers: %s', result.get('error'))
        return [], {}

    items = result['response']
    subscriber_count = 0
    non_subscriber_count = 0
    skipped_system_count = 0
    handlers = []
    all_handlers_by_id = {}

    for item in items:
        object_id = clean(item.get('ObjectId'))
        display_name = clean(item.get('DisplayName'))
        is_subscriber = bool(item.get('RecipientSubscriberObjectId'))

        if object_id:
            all_handlers_by_id[object_id] = {
                'displayName': display_name,
                'isSubscriber': is_subscriber,
            }

        if is_subscriber:
            subscriber_count += 1
            continue

        non_subscriber_count += 1
        if display_name in SKIP_HANDLERS:
            skipped_system_count += 1
            continue

        handlers.append({
            'displayName': display_name,
            'extension': clean(item.get('DtmfAccessId')),
            'objectId': object_id,
            'uri': clean(item.get('URI')),
        })

    handlers.sort(key=lambda row: (row['displayName'].casefold(), row['objectId']))

    logger.info('Unique handler records processed: %d', len(items))
    logger.info('Subscriber handlers excluded: %d', subscriber_count)
    logger.info('Non-subscriber handlers found: %d', non_subscriber_count)
    logger.info('Built-in/system handlers excluded: %d', skipped_system_count)
    logger.info('Call handlers to export: %d', len(handlers))
    logger.info('All-handler lookup records retained: %d', len(all_handlers_by_id))

    return handlers, all_handlers_by_id


def write_call_handlers_csv(handlers, csv_file, logger):
    """Write the non-subscriber Call Handlers CSV."""
    fields = ['displayName', 'extension', 'objectId', 'uri']
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(handlers)
    logger.info('Exported %d Call Handlers to %s', len(handlers), csv_file)


def classify_destination(entry, target_handler_name, subscriber_name):
    """
    Classify a MenuEntry's destination.

    Args:
        entry (dict): raw MenuEntry dict
        target_handler_name (str): DisplayName of the target handler, if it is
            a non-subscriber handler that was exported
        subscriber_name (str): DisplayName of the target handler, if it is a
            subscriber mailbox

    Returns:
        tuple: (destination_type, destination_name)
    """
    transfer_number = clean(entry.get('TransferNumber'))
    transfer_display_name = clean(entry.get('DisplayName'))
    target_handler_id = clean(entry.get('TargetHandlerObjectId'))
    target_conversation = clean(entry.get('TargetConversation'))

    if transfer_number:
        return 'Transfer', transfer_display_name or transfer_number

    if target_handler_id:
        if target_handler_name:
            return 'Call Handler', target_handler_name
        if subscriber_name:
            return 'Subscriber Mailbox', subscriber_name
        return 'Unknown Handler', target_handler_id

    if target_conversation:
        return 'Conversation', target_conversation

    return 'No configured destination', ''


def get_menu_entries_for_handlers(cuc, handlers, all_handlers_by_id, logger):
    """
    Retrieve MenuEntries for every handler and classify each entry's destination.

    Args:
        cuc: CUC API client instance
        handlers (list): non-subscriber handler dicts (from classify_call_handlers)
        all_handlers_by_id (dict): objectId -> {'displayName', 'isSubscriber'}
        logger: logger instance

    Returns:
        tuple: (output_rows, error_rows)
    """
    name_by_id = {row['objectId']: row['displayName'] for row in handlers if row['objectId']}
    output = []
    errors = []
    total_handlers = len(handlers)
    logger.info('Retrieving MenuEntries for %d Call Handlers', total_handlers)

    for index, handler in enumerate(handlers, start=1):
        source_name = handler['displayName']
        source_id = handler['objectId']

        result = cuc.get_menu_entries(source_id)
        if not result.get('success'):
            logger.error('MenuEntries failed for %s: %s', source_name, result.get('error'))
            errors.append({
                'sourceHandler': source_name,
                'sourceExtension': handler['extension'],
                'sourceObjectId': source_id,
                'menuUrl': f'handlers/callhandlers/{source_id}/menuentries',
                'error': result.get('error'),
            })
            continue

        menu_entries = result['response']
        for entry in menu_entries:
            target_id = clean(entry.get('TargetHandlerObjectId'))
            target_name = name_by_id.get(target_id, '')
            subscriber_name = ''
            if not target_name and target_id in all_handlers_by_id and all_handlers_by_id[target_id]['isSubscriber']:
                subscriber_name = all_handlers_by_id[target_id]['displayName']
            destination_type, destination_name = classify_destination(entry, target_name, subscriber_name)
            locked = clean(entry.get('Locked')).lower()
            if locked == 'true':
                locked = 'TRUE'
            elif locked == 'false':
                locked = 'FALSE'
            else:
                locked = ''

            output.append({
                'sourceHandler': source_name,
                'sourceExtension': handler['extension'],
                'sourceObjectId': source_id,
                'touchToneKey': clean(entry.get('TouchtoneKey')),
                'locked': locked,
                'actionCode': clean(entry.get('Action')),
                'destinationType': destination_type,
                'destinationName': destination_name,
                'targetConversation': clean(entry.get('TargetConversation')),
                'targetHandlerObjectId': target_id,
                'targetHandlerName': target_name,
                'transferDisplayName': clean(entry.get('DisplayName')),
                'transferNumber': clean(entry.get('TransferNumber')),
                'transferType': clean(entry.get('TransferType')),
                'transferRings': clean(entry.get('TransferRings')),
                'menuEntryObjectId': clean(entry.get('ObjectId')),
                'menuEntryUri': clean(entry.get('URI')),
            })

        logger.info('MenuEntries %d/%d: %s - %d entries', index, total_handlers, source_name, len(menu_entries))

    key_order = {str(i): i for i in range(10)}
    key_order.update({'*': 10, '#': 11})
    output.sort(key=lambda row: (
        row['sourceHandler'].casefold(),
        key_order.get(row['touchToneKey'], 99),
        row['destinationName'].casefold(),
    ))
    logger.info('Collected %d total MenuEntry records', len(output))
    logger.info('MenuEntry handler failures: %d', len(errors))
    return output, errors


def write_menu_entries_csv(rows, csv_file, logger):
    """Write the MenuEntry CSV."""
    fields = [
        'sourceHandler', 'sourceExtension', 'sourceObjectId', 'touchToneKey',
        'locked', 'actionCode', 'destinationType', 'destinationName',
        'targetConversation', 'targetHandlerObjectId', 'targetHandlerName',
        'transferDisplayName', 'transferNumber', 'transferType', 'transferRings',
        'menuEntryObjectId', 'menuEntryUri',
    ]
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    logger.info('Exported %d MenuEntry records to %s', len(rows), csv_file)


def write_errors_csv(errors, csv_file, logger):
    """Write the MenuEntry errors CSV."""
    fields = ['sourceHandler', 'sourceExtension', 'sourceObjectId', 'menuUrl', 'error']
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(errors)
    logger.info('Exported %d MenuEntry errors to %s', len(errors), csv_file)


def output_path_for_cluster(csv_file, cluster_name, suffix):
    """Return csv_file, or csv_file with '-<cluster_name>' inserted before the extension when suffix is True."""
    if not suffix:
        return csv_file
    path = Path(csv_file)
    return str(path.with_name(f'{path.stem}-{cluster_name}{path.suffix}'))


def run_operation_on_cluster(basepath, cluster_data, handler_csv, menu_csv, cluster_credentials, logger, suffix=False):
    """
    Export non-subscriber Call Handlers and MenuEntries for a single cluster.

    Args:
        basepath (Path): repo cuc/ directory
        cluster_data (dict): cluster dict from clusters.csv (name, server, version)
        handler_csv (str): requested Call Handler CSV output path
        menu_csv (str): requested Menu Entry CSV output path
        cluster_credentials (dict): cluster_name -> (username, password)
        logger: logger instance
        suffix (bool): if True, suffix output filenames with '-<cluster_name>'

    Returns:
        bool: True on success, False on any exception
    """
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        username, password = cluster_credentials[cluster_name]
        version = cluster_data.get('version')

        cuc = CUC(username=username, password=password, server=server, version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        handlers, all_handlers_by_id = classify_call_handlers(cuc, logger)
        handler_output = output_path_for_cluster(handler_csv, cluster_name, suffix)
        write_call_handlers_csv(handlers, handler_output, logger)

        menu_entries, errors = get_menu_entries_for_handlers(cuc, handlers, all_handlers_by_id, logger)
        menu_output = output_path_for_cluster(menu_csv, cluster_name, suffix)
        write_menu_entries_csv(menu_entries, menu_output, logger)

        error_output = Path(menu_output).with_name(Path(menu_output).stem + '_errors.csv')
        write_errors_csv(errors, error_output, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        print(f"  Call Handlers: {handler_output}")
        print(f"  Menu Entries: {menu_output}")
        print(f"  Menu Entry Errors: {error_output}")
        return True
    except Exception as e:
        logger.error('Exception on cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, handler_csv, menu_csv, logger):
    """Export non-subscriber Call Handlers and MenuEntries for every selected cluster."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("=" * 80)
    print("Loading Credentials")
    print("=" * 80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)
    cluster_credentials = load_credentials_for_multi_objects('CUC', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, handler_csv, menu_csv, cluster_credentials, logger, suffix=True):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-list-nonsubscriber-call-handlers.log"
    logger = setup_logger(log_file)
    logger.info("List Non-Subscriber Call Handlers - Started")

    basepath = Path.cwd()

    default_handler_csv = str(basepath.parent / '_DATA' / 'non_subscriber_callhandlers.csv')
    handler_csv = input(f'Call Handler CSV Output [{default_handler_csv}]: ').strip() or default_handler_csv

    default_menu_csv = str(basepath.parent / '_DATA' / 'menuentries.csv')
    menu_csv = input(f'Menu Entry CSV Output [{default_menu_csv}]: ').strip() or default_menu_csv

    clusters_data = get_objects_for_multi_operation(basepath, 'CUC', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_use_multiple(len(clusters_data), 'clusters', default=False)
        if use_multiple:
            run_on_all_clusters(basepath, clusters_data, handler_csv, menu_csv, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)
            username, password = load_credentials('CUC', cluster['name'])
            cluster_credentials = {cluster['name']: (username, password)}
            run_operation_on_cluster(basepath, cluster, handler_csv, menu_csv, cluster_credentials, logger)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)
        username, password = load_credentials('CUC', cluster['name'])
        cluster_credentials = {cluster['name']: (username, password)}
        run_operation_on_cluster(basepath, cluster, handler_csv, menu_csv, cluster_credentials, logger)

    logger.info("List Non-Subscriber Call Handlers - Completed")
