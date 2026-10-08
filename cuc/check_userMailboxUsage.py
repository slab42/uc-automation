#!/usr/bin/env python3
# TITLE: Mailbox Export Usage

"""
Export user mailbox usage from Cisco Unity Connection to CSV.

Query users by extension (DtmfAccessId) and export mailbox size data:
dtmfAccessID, alias, mailboxSize

Usage:
    python3 check_userMailboxUsage.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use multiple clusters?: (y/n): choose 'y' to run against every CUC cluster
        in clusters.csv, or 'n' (default) to pick a single cluster.
    Use CSV?: (y/n): choose 'y' to export mailbox usage for multiple users from a CSV file,
        or 'n' (default) to check a single user's mailbox.

    If 'n' (single user):
        Extension: the extension number to look up

    If 'y' (CSV):
        Enter CSV file name or full path [_DATA/mailboxes.csv]: path to the CSV file
        Output file name [_DATA/mailbox_usage_report.csv]: path to output CSV file

CSV Input Format (extension):
2001
2002

CSV Output Format:
dtmfAccessID,alias,mailboxSize
2001,user1,123.45
2002,user2,456.78

Output: written to _DATA/mailbox_usage_report.csv by default. When run against multiple
clusters, each cluster's output file is suffixed with "-<cluster_name>" before .csv.
Logs: ../_logs/<timestamp>-check-user-mailbox-usage.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader, writer
import urllib3
from datetime import datetime
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no, prompt_use_multiple
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from cucAPI import CUC


def get_user_mailbox_usage(cuc, logger, extension):
    """
    Query a user by extension and retrieve mailbox size.

    Args:
        cuc (CUC): CUC API client
        logger: logger instance
        extension (string): Extension number (DtmfAccessId) to look up

    Returns:
        dict: {'success', 'dtmfAccessId', 'alias', 'mailboxSize', 'error'}
    """
    logger.info('Querying mailbox usage for DtmfAccessId: %s', extension)

    result = cuc.get_user_mailbox_usage(extension)
    if not result['success']:
        logger.warning('%s: %s', extension, result['error'])
        return {'success': False, 'dtmfAccessId': extension, 'alias': '', 'mailboxSize': '', 'error': result['error']}

    usage = result['response']
    logger.info(
        'Retrieved mailbox usage for %s (%s): %s bytes, %s MB',
        usage['alias'], usage['dtmfAccessId'], usage['byteSize'], usage['sizeMb']
    )
    return {
        'success': True,
        'dtmfAccessId': usage['dtmfAccessId'],
        'alias': usage['alias'],
        'mailboxSize': usage['sizeMb'],
        'error': ''
    }


def run_single_user(cuc, logger):
    """Export mailbox usage for a single user by extension."""
    extension = input('Extension: ')
    result = get_user_mailbox_usage(cuc, logger, extension)
    if result.get('success'):
        print(f"{result['dtmfAccessId']},{result['alias']},{result['mailboxSize']}")
    else:
        logger.error("Error for extension %s: %s", extension, result.get('error'))


def run_csv_file(cuc, logger, input_file, output_file):
    """Export mailbox usage for multiple users from a CSV file."""
    print('\nCSV must have a header row and contain one extension per row')
    print('Field: extension')

    try:
        with open(input_file, 'r', encoding='utf8') as my_file:
            csv_file = reader(my_file)
            next(my_file)

            output_rows = []
            row_count = 0
            for row in csv_file:
                if len(row) > 0:
                    extension = row[0].strip()
                    if extension:
                        row_count += 1
                        result = get_user_mailbox_usage(cuc, logger, extension)
                        if result.get('success'):
                            output_rows.append([result['dtmfAccessId'], result['alias'], result['mailboxSize']])
                        else:
                            logger.warning("Skipped extension %s: %s", extension, result.get('error'))

        with open(output_file, 'w', encoding='utf8', newline='') as out_file:
            csv_writer = writer(out_file)
            csv_writer.writerow(['dtmfAccessID', 'alias', 'mailboxSize'])
            csv_writer.writerows(output_rows)

        logger.info('Processed %s users from CSV', row_count)
        logger.info('Exported %s users to %s', len(output_rows), output_file)
        print(f'\nExported {len(output_rows)} users to {output_file}')
        return row_count, len(output_rows)

    except FileNotFoundError:
        logger.error('CSV file not found: %s', input_file)
        print(f'Error: CSV file not found: {input_file}')
        return 0, 0
    except IOError as e:
        logger.error('Error writing to output file: %s', str(e))
        print(f'Error writing to output file: {str(e)}')
        return 0, 0


def run_operation_on_cluster(cluster_data, operation_params, cluster_credentials, logger, suffix=False):
    """Run mailbox usage export on a single cluster."""
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
            output_file = operation_params['output_file']
            if suffix:
                base, dot, ext = output_file.rpartition('.')
                output_file = f'{base}-{cluster_name}.{ext}' if dot else f'{output_file}-{cluster_name}'
            run_csv_file(cuc, logger, operation_params['csv_file'], output_file)
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
    """Run mailbox usage export on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("=" * 80)
    print("Loading Credentials")
    print("=" * 80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUC', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(cluster, operation_params, cluster_credentials, logger, suffix=True):
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
    log_file = f"../_logs/{timestamp}-check-user-mailbox-usage.log"
    logger = setup_logger(log_file)
    logger.info("Check User Mailbox Usage - Started")

    default_csv = str(basepath.parent / '_DATA' / 'mailboxes.csv')
    default_output = str(basepath.parent / '_DATA' / 'mailbox_usage_report.csv')

    clusters_data = get_objects_for_multi_operation(basepath, 'CUC', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_use_multiple(len(clusters_data), 'clusters', default=False)
        if use_multiple:
            use_csv_mode = prompt_yes_no('Use CSV?', default=False)
            if use_csv_mode:
                print('\nCSV must have a header row and contain one extension per row')
                print('Field: extension')
                csv_file = input('Enter CSV file name or full path [_DATA/mailboxes.csv]: ') or default_csv
                output_file = input(f'Output file name [_DATA/mailbox_usage_report.csv]: ') or default_output
                operation_params = {'type': 'csv', 'csv_file': csv_file, 'output_file': output_file}
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

            use_csv_mode = prompt_yes_no('Use CSV?', default=False)
            if use_csv_mode:
                print('\nCSV must have a header row and contain one extension per row')
                print('Field: extension')
                csv_file = input('Enter CSV file name or full path [_DATA/mailboxes.csv]: ') or default_csv
                output_file = input(f'Output file name [_DATA/mailbox_usage_report.csv]: ') or default_output
                run_csv_file(cuc, logger, csv_file, output_file)
            else:
                run_single_user(cuc, logger)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUC', cluster['name'])
        cuc = CUC(username, password, cluster['server'], cluster['version'])

        use_csv_mode = prompt_yes_no('Use CSV?', default=False)
        if use_csv_mode:
            print('\nCSV must have a header row and contain one extension per row')
            print('Field: extension')
            csv_file = input('Enter CSV file name or full path [_DATA/mailboxes.csv]: ') or default_csv
            output_file = input(f'Output file name [_DATA/mailbox_usage_report.csv]: ') or default_output
            run_csv_file(cuc, logger, csv_file, output_file)
        else:
            run_single_user(cuc, logger)

    logger.info("Check User Mailbox Usage - Completed")
