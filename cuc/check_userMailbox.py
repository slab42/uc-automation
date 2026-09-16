#!/usr/bin/env python3

"""
Check user mailbox status in Cisco Unity Connection.

Query users by extension (field varies by CUC version) and display mailbox information
such as current size, quotas, and quota status.

CUC Version Support:
- CUC 15.4+: Uses DtmfAccessId field
- CUC < 15.4: Uses Extension field

Usage:
    python3 check_userMailbox.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use CSV?: (y/n): choose 'y' to check mailboxes for multiple users from a CSV file,
        or 'n' (default) to check a single user's mailbox.

    If 'n' (single user):
        Extension: the extension number to look up

    If 'y' (CSV):
        Enter CSV file name or full path: path to the CSV file
            (default: mailboxes.csv)

CSV Format:
extension
2001
2002

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader
import time
import requests
import urllib3
from requests.auth import HTTPBasicAuth
from datetime import datetime
from lxml import etree
from setup.logger import setup_logger
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)

log_filename_prefix = 'check-userMailbox-'


def get_extension_field(version):
    """
    Determine which field to query based on CUC version.

    Args:
        version (string): CUC version (e.g., '15.0', '15.4')

    Returns:
        string: Field name to use for extension lookup
    """
    try:
        version_float = float(version)
        if version_float >= 15.4:
            return 'DtmfAccessId'
        else:
            return 'DtmfAccessId'
    except (ValueError, TypeError):
        logger.warning(f'Could not parse version {version}, defaulting to DtmfAccessId')
        return 'DtmfAccessId'


def check_user_mailbox(http_session, cuc_server, extension, version):
    """
    Query a user by extension and retrieve mailbox information.

    Args:
        http_session: Requests session with auth configured
        cuc_server (string): CUC server address
        extension (string): Extension number to look up
        version (string): CUC version to determine field to query

    Returns:
        dict: Result with keys 'success', 'response', 'error'
    """
    try:
        base_url = f'https://{cuc_server}/vmrest'
        extension_field = get_extension_field(version)

        logger.info(f'Searching for user with {extension_field}: {extension} (CUC version: {version})')

        users_url = f'{base_url}/users/'
        users_response = http_session.get(users_url, verify=False)
        users_response.raise_for_status()

        root = etree.fromstring(users_response.content)
        user_elements = root.findall('.//User')

        matched_user = None
        for user_elem in user_elements:
            user_dict = {}
            for child in user_elem:
                user_dict[child.tag] = child.text

            if user_dict.get(extension_field) == extension:
                matched_user = user_dict
                break

        if not matched_user:
            logger.warning(f'No user found with {extension_field}: {extension}')
            return {'success': False, 'response': '', 'error': f'No user found with {extension_field}: {extension}'}

        user_display_name = matched_user.get('DisplayName', 'N/A')
        user_alias = matched_user.get('Alias', 'N/A')
        user_uri = matched_user.get('URI', '')

        logger.info(f'Found user: {user_display_name} (Alias: {user_alias})')

        if not user_uri:
            logger.error(f'No URI found for user {user_display_name}')
            return {'success': False, 'response': '', 'error': f'No URI found for user {user_display_name}'}

        mailbox_url = f'https://{cuc_server}{user_uri}/mailboxattributes'
        mailbox_response = http_session.get(mailbox_url, verify=False)
        mailbox_response.raise_for_status()

        mailbox_root = etree.fromstring(mailbox_response.content)
        mailbox = {}
        if mailbox_root.tag == 'MailboxAttributes':
            for child in mailbox_root:
                mailbox[child.tag] = child.text
        else:
            mailbox_elem = mailbox_root.find('.//MailboxAttributes')
            if mailbox_elem is not None:
                for child in mailbox_elem:
                    mailbox[child.tag] = child.text

        current_size_bytes = int(mailbox.get('ByteSize', 0))
        current_size_mb = current_size_bytes / (1024 * 1024)

        warning_quota = int(mailbox.get('WarningQuota', 0))
        receive_quota = int(mailbox.get('ReceiveQuota', 0))
        send_quota = int(mailbox.get('SendQuota', 0))

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
        {extension_field}: {extension}
        Display Name: {user_display_name}
        Alias: {user_alias}

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

    except requests.exceptions.RequestException as e:
        error_msg = f'API request failed: {str(e)}'
        logger.error(error_msg)
        return {'success': False, 'response': '', 'error': error_msg}
    except (KeyError, ValueError) as e:
        error_msg = f'Error parsing response: {str(e)}'
        logger.error(error_msg)
        return {'success': False, 'response': '', 'error': error_msg}


def run_single_user(http_session, cuc_server, version, logger):
    """Check mailbox for a single user by extension."""
    extension = input('Extension: ')
    result = check_user_mailbox(http_session, cuc_server, extension, version)
    if result.get('success'):
        print(result.get('response'))
    else:
        print(f"Error: {result.get('error')}")


def run_csv_file(http_session, cuc_server, version, logger, csv_file_path):
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
                        result = check_user_mailbox(http_session, cuc_server, extension, version)
                        if result.get('success'):
                            print(result.get('response'))
                        else:
                            print(f"Error for extension {extension}: {result.get('error')}")
            logger.info(f'Processed {row_count} users from CSV')
    except FileNotFoundError:
        logger.error(f'CSV file not found: {csv_file_path}')
        print(f'Error: CSV file not found: {csv_file_path}')


def run_operation_on_cluster(cluster_data, operation_params, cluster_credentials, logger):
    """Run mailbox check on a single cluster."""
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        http_session = requests.Session()
        http_session.auth = HTTPBasicAuth(username, password)
        http_session.headers.update({'Content-Type': 'application/json'})

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        op_type = operation_params.get('type')
        if op_type == 'csv':
            run_csv_file(http_session, server, version, logger, operation_params['csv_file'])
        else:  # single
            run_single_user(http_session, server, version, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(clusters_data, operation_params, logger):
    """Run mailbox check on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = input('Use same credentials for all clusters? (y/n) [default: y]: ').strip().lower()
    use_same = use_same in ('', 'y', 'yes')

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
    log_file = f"../_logs/{timestamp}-check-usermailbox.log"
    logger = setup_logger(log_file)
    logger.info("Check User Mailbox - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUC')
    if clusters_data:
        response = input(f'{len(clusters_data)} clusters found. Use multiple clusters?: (y/n) ') or 'n'
        if response.lower() in ('y', 'yes'):
            # Gather operation parameters for multi-cluster
            input_type_csv = input('Use CSV?: (y/n) ') or 'n'
            if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
                print('\nCSV must have a header row and contain one extension per row')
                print('Field: extension')
                csv_file = input('Enter CSV file name or full path: ') or 'mailboxes.csv'
                operation_params = {'type': 'csv', 'csv_file': csv_file}
            else:
                operation_params = {'type': 'single'}
            run_on_all_clusters(clusters_data, operation_params, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUC')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUC', cluster['name'])
            cuc_server = cluster['server']
            version = cluster['version']

            logger.info(f'Starting check_userMailbox for server: {cuc_server} (version: {version})')
            extension_field = get_extension_field(version)
            logger.info(f'Using field: {extension_field} for extension lookup')

            http_session = requests.Session()
            http_session.auth = HTTPBasicAuth(username, password)
            http_session.headers.update({'Content-Type': 'application/json'})

            input_type_csv = input('Use CSV?: (y/n) ') or 'n'
            if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
                print('\nCSV must have a header row and contain one extension per row')
                print('Field: extension')
                csv_file = input('Enter CSV file name or full path: ') or 'mailboxes.csv'
                run_csv_file(http_session, cuc_server, version, logger, csv_file)
            else:
                run_single_user(http_session, cuc_server, version, logger)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUC')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUC', cluster['name'])
        cuc_server = cluster['server']
        version = cluster['version']

        logger.info(f'Starting check_userMailbox for server: {cuc_server} (version: {version})')
        extension_field = get_extension_field(version)
        logger.info(f'Using field: {extension_field} for extension lookup')

        http_session = requests.Session()
        http_session.auth = HTTPBasicAuth(username, password)
        http_session.headers.update({'Content-Type': 'application/json'})

        input_type_csv = input('Use CSV?: (y/n) ') or 'n'
        if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
            print('\nCSV must have a header row and contain one extension per row')
            print('Field: extension')
            csv_file = input('Enter CSV file name or full path: ') or 'mailboxes.csv'
            run_csv_file(http_session, cuc_server, version, logger, csv_file)
        else:
            run_single_user(http_session, cuc_server, version, logger)

    logger.info('Script completed')
