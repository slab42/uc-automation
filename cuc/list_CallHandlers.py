#!/usr/bin/env python3
# TITLE: List Call Handlers

"""
List Cisco Unity Connection Call Handlers to CSV.

Query all Call Handlers from CUC and export displayName, extension, and
objectId to CSV. Skips a fixed set of built-in system handlers and any
subscriber (user) handler.

Usage:
    python3 list_CallHandlers.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use multiple clusters?: (y/n): choose 'y' to run against every CUC cluster
        in clusters.csv, or 'n' (default) to pick a single cluster.
    Output CSV file [_DATA/callhandlers.csv]: path to save the output CSV file.
        In multi-cluster mode, each cluster's output is suffixed with
        -<cluster_name> so clusters do not overwrite each other.

CSV Output Format (displayName, extension, objectId):
Call Handler Name,2000,ca8cdbd5-9b1b-4893-9237-171d78b5c6a2
Another Handler,2001,f349f979-308b-4fad-b110-f58c132c2cae

Output: _DATA/callhandlers.csv (default; use with delete_CallHandlers.py)
Logs: ../_logs/<timestamp>-list-call-handlers.log
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
from setup.prompt_utils import prompt_yes_no
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


def get_call_handlers(cuc, logger):
    """
    Query all Call Handlers from CUC and filter out system and subscriber handlers.

    Args:
        cuc: CUC API client instance
        logger: logger instance

    Returns:
        list: List of dicts with keys 'displayName', 'extension', 'objectId'
    """
    logger.info('Retrieving Call Handlers from %s', cuc.server)
    result = cuc.list_call_handlers()
    if not result.get('success'):
        logger.error('Failed to retrieve Call Handlers: %s', result.get('error'))
        return []

    handlers = []
    for item in result['response']:
        display_name = item.get('DisplayName', '')
        extension = item.get('DtmfAccessId', '')
        is_user_handler = bool(item.get('RecipientSubscriberObjectId'))

        if display_name not in SKIP_HANDLERS and not is_user_handler:
            handlers.append({
                'displayName': display_name,
                'extension': extension,
                'objectId': item.get('ObjectId', '')
            })

    logger.info('Found %d Call Handlers', len(handlers))
    return handlers


def write_to_csv(handlers, csv_file, logger):
    """
    Write Call Handlers to CSV file.

    Args:
        handlers (list): List of handler dicts with displayName, extension, and objectId
        csv_file (str): Path to output CSV file
        logger: logger instance
    """
    with open(csv_file, 'w', newline='', encoding='utf8') as f:
        writer = csv.DictWriter(f, fieldnames=['displayName', 'extension', 'objectId'])
        writer.writeheader()
        writer.writerows(handlers)

    logger.info('Exported %d Call Handlers to %s', len(handlers), csv_file)
    print(f'\nSuccessfully exported Call Handlers to: {csv_file}')


def output_path_for_cluster(csv_file, cluster_name, suffix):
    """Return csv_file, or csv_file with '-<cluster_name>' inserted before the extension when suffix is True."""
    if not suffix:
        return csv_file
    path = Path(csv_file)
    return str(path.with_name(f'{path.stem}-{cluster_name}{path.suffix}'))


def run_operation_on_cluster(basepath, cluster_data, csv_file, cluster_credentials, logger, suffix=False):
    """
    Export Call Handlers for a single cluster.

    Args:
        basepath (Path): repo cuc/ directory
        cluster_data (dict): cluster dict from clusters.csv (name, server, version)
        csv_file (str): requested output CSV path (base path, before suffixing)
        cluster_credentials (dict): cluster_name -> (username, password)
        logger: logger instance
        suffix (bool): if True, suffix the output filename with '-<cluster_name>'

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

        handlers = get_call_handlers(cuc, logger)
        output_file = output_path_for_cluster(csv_file, cluster_name, suffix)
        write_to_csv(handlers, output_file, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error('Exception on cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, csv_file, logger):
    """Export Call Handlers for every selected cluster, one output file per cluster."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("=" * 80)
    print("Loading Credentials")
    print("=" * 80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)
    cluster_credentials = load_credentials_for_multi_objects('CUC', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, csv_file, cluster_credentials, logger, suffix=True):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-list-call-handlers.log"
    logger = setup_logger(log_file)
    logger.info("List Call Handlers - Started")

    basepath = Path.cwd()

    default_csv = str(basepath.parent / '_DATA' / 'callhandlers.csv')
    csv_file = input(f'Output CSV file [{default_csv}]: ').strip() or default_csv

    clusters_data = get_objects_for_multi_operation(basepath, 'CUC', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            run_on_all_clusters(basepath, clusters_data, csv_file, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)
            username, password = load_credentials('CUC', cluster['name'])
            cluster_credentials = {cluster['name']: (username, password)}
            run_operation_on_cluster(basepath, cluster, csv_file, cluster_credentials, logger)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)
        username, password = load_credentials('CUC', cluster['name'])
        cluster_credentials = {cluster['name']: (username, password)}
        run_operation_on_cluster(basepath, cluster, csv_file, cluster_credentials, logger)

    logger.info("List Call Handlers - Completed")
