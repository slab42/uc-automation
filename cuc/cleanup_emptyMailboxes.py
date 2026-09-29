#!/usr/bin/env python3
# TITLE: Clean Up Empty Mailboxes

"""
Clean up empty mailboxes from Cisco Unity Connection.

Reads a list of extensions from a CSV file, looks up each user's mailbox size,
and deletes the USER ACCOUNT (not just the mailbox) for any mailbox with 0 bytes
of usage. Mailboxes with data are left alone and written to an output CSV so
they can be reviewed later.

Deleting an empty mailbox deletes the entire user account via the CUC REST API;
there is no way to remove only the mailbox and keep the user.

Usage:
    python3 cleanup_emptyMailboxes.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use multiple clusters?: (y/n): choose 'y' to run against every CUC cluster
        in clusters.csv, or 'n' (default) to pick a single cluster.
    Prompt for deletes?: (y/n): choose 'y' to be prompted before deleting each
        empty mailbox's user account, or 'n' (default) to delete all empty
        mailboxes automatically.
    Input CSV file name [_DATA/mailboxes.csv]: path to the CSV file with extensions
    Output file name [_DATA/mailbox_usage_remaining.csv]: path to output CSV file
        with mailboxes that have >0 size

CSV Input Format (1 column, any header name):
extension
2001
2002

CSV Output Format (remaining mailboxes):
dtmfAccessID,alias,mailboxSize
2002,user2,123.45

Output: written to _DATA/mailbox_usage_remaining.csv by default. When run against
multiple clusters, each cluster's output file is suffixed with "-<cluster_name>" before .csv.
Logs: ../_logs/<timestamp>-cleanup-empty-mailboxes.log
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader, writer
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


def process_mailboxes(cuc, logger, input_file, output_file, prompt_for_deletes):
    """
    Process mailbox CSV: look up mailbox sizes, delete empty ones (deletes the user
    account), and export mailboxes with data to a new CSV.

    Args:
        cuc (CUC): CUC API client
        logger: logger instance
        input_file (string): Path to input CSV with extensions (1 column, any header)
        output_file (string): Path to output CSV with remaining mailboxes
        prompt_for_deletes (bool): Whether to prompt before deleting each user account

    Returns:
        tuple: (checked_count, deleted_count, error_count, len(output_rows)) or None on file error
    """
    try:
        with open(input_file, 'r', encoding='utf8') as my_file:
            csv_file = reader(my_file)
            next(my_file)  # Skip header

            output_rows = []
            deleted_count = 0
            error_count = 0
            checked_count = 0

            for row in csv_file:
                if len(row) > 0:
                    extension = row[0].strip()

                    if extension:
                        checked_count += 1
                        logger.debug('Looking up mailbox for extension: %s', extension)

                        mailbox_info = cuc.get_user_mailbox_usage(extension)

                        if not mailbox_info['success']:
                            logger.warning('Could not retrieve mailbox info for %s: %s', extension, mailbox_info['error'])
                            error_count += 1
                            continue

                        usage = mailbox_info['response']
                        dtmf_access_id = usage['dtmfAccessId']
                        alias = usage['alias']
                        mailbox_size = usage['sizeMb']
                        user_uri = usage['uri']

                        logger.debug('Checking mailbox: %s (%s) - Size: %s MB', dtmf_access_id, alias, mailbox_size)

                        if mailbox_size == 0:
                            logger.info('Empty mailbox found: %s (%s) - 0 MB', dtmf_access_id, alias)
                            should_delete = True
                            if prompt_for_deletes:
                                should_delete = prompt_yes_no(f'Delete user account for empty mailbox {dtmf_access_id} ({alias})?', default=False)

                            if should_delete:
                                delete_result = cuc.delete_user(user_uri)
                                if delete_result['success']:
                                    logger.info('Deleted: %s (%s)', dtmf_access_id, alias)
                                    deleted_count += 1
                                else:
                                    logger.warning('Could not delete %s: %s', dtmf_access_id, delete_result['error'])
                            else:
                                logger.info('Skipped deletion of %s (%s)', dtmf_access_id, alias)
                        else:
                            logger.info('Retaining mailbox: %s (%s) - %s MB', dtmf_access_id, alias, mailbox_size)
                            output_rows.append([dtmf_access_id, alias, mailbox_size])

        with open(output_file, 'w', encoding='utf8', newline='') as out_file:
            csv_writer = writer(out_file)
            csv_writer.writerow(['dtmfAccessID', 'alias', 'mailboxSize'])
            csv_writer.writerows(output_rows)

        logger.info('Processed %s extensions', checked_count)
        logger.info('Deleted %s empty mailboxes', deleted_count)
        logger.info('Encountered %s errors during processing', error_count)
        logger.info('Exported %s mailboxes with data to %s', len(output_rows), output_file)
        print('\nResults:')
        print(f'  Checked: {checked_count} extensions')
        print(f'  Deleted: {deleted_count} empty mailboxes')
        print(f'  Errors: {error_count}')
        print(f'  Exported: {len(output_rows)} mailboxes to {output_file}')

        return checked_count, deleted_count, error_count, len(output_rows)

    except FileNotFoundError:
        logger.error('CSV file not found: %s', input_file)
        print(f'Error: CSV file not found: {input_file}')
        return None
    except IOError as e:
        logger.error('Error reading/writing file: %s', str(e))
        print(f'Error: {str(e)}')
        return None


def run_operation_on_cluster(cluster_data, operation_params, cluster_credentials, logger, suffix=False):
    """Run empty mailbox cleanup on a single cluster."""
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

        output_file = operation_params['output_file']
        if suffix:
            base, dot, ext = output_file.rpartition('.')
            output_file = f'{base}-{cluster_name}.{ext}' if dot else f'{output_file}-{cluster_name}'

        process_mailboxes(cuc, logger, operation_params['input_file'], output_file, operation_params['prompt_for_deletes'])

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error("Exception on cluster %s: %s", cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(clusters_data, operation_params, logger):
    """Run empty mailbox cleanup on all clusters sequentially."""
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
    log_file = f"../_logs/{timestamp}-cleanup-empty-mailboxes.log"
    logger = setup_logger(log_file)
    logger.info("Cleanup Empty Mailboxes - Started")

    default_csv = str(basepath.parent / '_DATA' / 'mailboxes.csv')
    default_output = str(basepath.parent / '_DATA' / 'mailbox_usage_remaining.csv')

    clusters_data = get_objects_for_multi_operation(basepath, 'CUC', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            prompt_for_deletes = prompt_yes_no('Prompt for deletes?', default=False)
            input_file = input('Input CSV file name [_DATA/mailboxes.csv]: ') or default_csv
            output_file = input('Output file name [_DATA/mailbox_usage_remaining.csv]: ') or default_output
            operation_params = {'input_file': input_file, 'output_file': output_file, 'prompt_for_deletes': prompt_for_deletes}
            run_on_all_clusters(clusters_data, operation_params, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUC', cluster['name'])
            cuc = CUC(username, password, cluster['server'], cluster['version'])

            prompt_for_deletes = prompt_yes_no('Prompt for deletes?', default=False)
            input_file = input('Input CSV file name [_DATA/mailboxes.csv]: ') or default_csv
            output_file = input('Output file name [_DATA/mailbox_usage_remaining.csv]: ') or default_output

            process_mailboxes(cuc, logger, input_file, output_file, prompt_for_deletes)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUC', cluster['name'])
        cuc = CUC(username, password, cluster['server'], cluster['version'])

        prompt_for_deletes = prompt_yes_no('Prompt for deletes?', default=False)
        input_file = input('Input CSV file name [_DATA/mailboxes.csv]: ') or default_csv
        output_file = input('Output file name [_DATA/mailbox_usage_remaining.csv]: ') or default_output

        process_mailboxes(cuc, logger, input_file, output_file, prompt_for_deletes)

    logger.info("Cleanup Empty Mailboxes - Completed")
