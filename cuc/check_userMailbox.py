#!/usr/bin/env python3
# TITLE: Check User Mailbox Status

"""
Check user mailbox status in Cisco Unity Connection.

Query a user by extension (DtmfAccessId) and display mailbox information
such as current size, quotas, and quota status.

Usage:
    python3 check_userMailbox.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use multiple clusters?: (y/n): choose 'y' to run against every CUC cluster
        in clusters.csv, or 'n' (default) to pick a single cluster.
    Use CSV?: (y/n): choose 'y' to check mailboxes for multiple users from a CSV file,
        or 'n' (default) to check a single user's mailbox.

    If 'n' (single user):
        Extension: the extension number to look up

    If 'y' (CSV):
        Enter CSV file name or full path [_DATA/mailboxes.csv]: path to the CSV file

CSV format (extension):
2001
2002

Output: mailbox report is printed to the console (and logged) for each extension checked.
Logs: ../_logs/<timestamp>-check-user-mailbox.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader
import urllib3
from datetime import datetime
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from cucAPI import CUC


def check_user_mailbox(cuc, logger, extension):
    """
    Look up a user by extension and format their mailbox status.

    Args:
        cuc (CUC): CUC API client
        logger: logger instance
        extension (string): Extension number (DtmfAccessId) to look up

    Returns:
        dict: {'success': bool, 'response': <formatted text>, 'error': str}
    """
    logger.info('Searching for user with DtmfAccessId: %s', extension)

    result = cuc.get_user_mailbox_usage(extension)
    if not result['success']:
        logger.error(result['error'])
        return result

    usage = result['response']
    mailbox = usage['mailbox']

    current_size_bytes = int(mailbox.get('ByteSize') or 0)
    current_size_mb = current_size_bytes / (1024 * 1024)

    warning_quota = int(mailbox.get('WarningQuota') or 0)
    receive_quota = int(mailbox.get('ReceiveQuota') or 0)
    send_quota = int(mailbox.get('SendQuota') or 0)

    warning_quota_mb = warning_quota / (1024 * 1024) if warning_quota > 0 else 0
    receive_quota_mb = receive_quota / (1024 * 1024) if receive_quota > 0 else 0
    send_quota_mb = send_quota / (1024 * 1024) if send_quota > 0 else 0

    is_primary = mailbox.get('IsPrimary', 'false').lower() == 'true'
    is_store_mounted = mailbox.get('IsStoreMounted', 'false').lower() == 'true'
    is_mailbox_mounted = mailbox.get('IsMailboxMounted', 'false').lower() == 'true'
    is_store_overflow = mailbox.get('IsStoreOverFlowed', 'false').lower() == 'true'
    is_warning_exceeded = mailbox.get('IsWarningQuotaExceeded', 'false').lower() == 'true'
    is_receive_exceeded = mailbox.get('IsReceiveQuotaExceeded', 'false').lower() == 'true'
    is_send_exceeded = mailbox.get('IsSendQuotaExceeded', 'false').lower() == 'true'

    response_text = f"""
        DtmfAccessId: {usage['dtmfAccessId']}
        Display Name: {usage['displayName']}
        Alias: {usage['alias']}

        Mailbox Status:
          Primary: {is_primary}
          Store Mounted: {is_store_mounted}
          Mailbox Mounted: {is_mailbox_mounted}
          Store Overflow: {is_store_overflow}

        Mailbox Size:
          Current Size: {current_size_mb:.2f} MB ({current_size_bytes} bytes)

        Quotas:
          Warning Quota: {warning_quota_mb:.2f} MB
          Receive Quota: {receive_quota_mb:.2f} MB
          Send Quota: {send_quota_mb:.2f} MB

        Quota Exceeded Status:
          Warning Quota Exceeded: {is_warning_exceeded}
          Receive Quota Exceeded: {is_receive_exceeded}
          Send Quota Exceeded: {is_send_exceeded}
        """

    logger.info(response_text)
    return {'success': True, 'response': response_text, 'error': ''}


def run_single_user(cuc, logger):
    """Check mailbox for a single user by extension."""
    extension = input('Extension: ')
    result = check_user_mailbox(cuc, logger, extension)
    if result.get('success'):
        print(result.get('response'))
    else:
        print(f"Error: {result.get('error')}")


def run_csv_file(cuc, logger, csv_file_path):
    """Check mailboxes for multiple users from a CSV file."""
    print('\nCSV must have a header row and contain one extension per row')
    print('Field: extension')

    try:
        with open(csv_file_path, 'r', encoding='utf8') as my_file:
            csv_file = reader(my_file)
            next(my_file)
            row_count = 0
            for row in csv_file:
                if len(row) > 0:
                    extension = row[0].strip()
                    if extension:
                        row_count += 1
                        result = check_user_mailbox(cuc, logger, extension)
                        if result.get('success'):
                            print(result.get('response'))
                        else:
                            print(f"Error for extension {extension}: {result.get('error')}")
            logger.info('Processed %s users from CSV', row_count)
    except FileNotFoundError:
        logger.error('CSV file not found: %s', csv_file_path)
        print(f'Error: CSV file not found: {csv_file_path}')


def run_operation_on_cluster(cluster_data, operation_params, cluster_credentials, logger):
    """Run mailbox check on a single cluster."""
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]
        cuc = CUC(username, password, server, version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        op_type = operation_params.get('type')
        if op_type == 'csv':
            run_csv_file(cuc, logger, operation_params['csv_file'])
        else:  # single
            run_single_user(cuc, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error("Exception on cluster %s: %s", cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(clusters_data, operation_params, logger):
    """Run mailbox check on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("=" * 80)
    print("Loading Credentials")
    print("=" * 80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUC', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(cluster, operation_params, cluster_credentials, logger):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    basepath = Path.cwd()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-check-user-mailbox.log"
    logger = setup_logger(log_file)
    logger.info("Check User Mailbox - Started")

    default_csv = str(basepath.parent / '_DATA' / 'mailboxes.csv')

    clusters_data = get_objects_for_multi_operation(basepath, 'CUC', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV must have a header row and contain one extension per row')
                print('Field: extension')
                csv_file = input(f'Enter CSV file name or full path [_DATA/mailboxes.csv]: ') or default_csv
                operation_params = {'type': 'csv', 'csv_file': csv_file}
            else:
                operation_params = {'type': 'single'}
            run_on_all_clusters(clusters_data, operation_params, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUC', cluster['name'])
            cuc = CUC(username, password, cluster['server'], cluster['version'])

            input_type_csv = prompt_yes_no('Use CSV?', default=False)
            if input_type_csv:
                print('\nCSV must have a header row and contain one extension per row')
                print('Field: extension')
                csv_file = input(f'Enter CSV file name or full path [_DATA/mailboxes.csv]: ') or default_csv
                run_csv_file(cuc, logger, csv_file)
            else:
                run_single_user(cuc, logger)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUC', cluster['name'])
        cuc = CUC(username, password, cluster['server'], cluster['version'])

        input_type_csv = prompt_yes_no('Use CSV?', default=False)
        if input_type_csv:
            print('\nCSV must have a header row and contain one extension per row')
            print('Field: extension')
            csv_file = input(f'Enter CSV file name or full path [_DATA/mailboxes.csv]: ') or default_csv
            run_csv_file(cuc, logger, csv_file)
        else:
            run_single_user(cuc, logger)

    logger.info("Check User Mailbox - Completed")
