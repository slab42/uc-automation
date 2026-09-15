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
    CUC JSON File (cuc-info.json): path to the JSON file with server/login
        info (default: cuc-info.json). If the password field in that file
        is blank, you will be prompted to enter it.
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
from csv import reader
import json
import sys
import time
import requests
import urllib3
from requests.auth import HTTPBasicAuth
import base64
import logging
from logging.handlers import RotatingFileHandler
import os
import getpass
from lxml import etree

log_filename_prefix = 'check-userMailbox-'

def setup_logger(log_path):
    """Setup a custom logger to handle file and stdout logging."""
    logger = logging.getLogger('cuc_logger')
    logger.setLevel(logging.DEBUG)

    message_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(message_format)

    log_split = str(log_path).rsplit('/', 1)
    path_exists = os.path.isdir(log_split[0])
    if path_exists == False:
        try:
            os.makedirs(log_split[0])
        except OSError as e:
            print(f'Unable to create logging directory. Please check permissions\n {e}')

    log_file_handler = RotatingFileHandler(log_path, maxBytes=500000, backupCount=5)
    log_file_handler.setFormatter(message_format)

    logger.addHandler(log_file_handler)
    logger.addHandler(stdout_handler)
    return logger


def load_server_config(config_file):
    """Load CUC server configuration from JSON file.

    Args:
        config_file (Path): Path to JSON config file

    Returns:
        dict: Configuration with keys: server, username, password, version
    """
    with open(config_file) as json_data_file:
        config = json.load(json_data_file)

    return config


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


def single_user():
    """Check mailbox for a single user by extension."""
    extension = input('Extension: ')
    result = check_user_mailbox(http_session, cuc_server, extension, version)
    if result.get('success'):
        print(result.get('response'))
    else:
        print(f"Error: {result.get('error')}")


def use_csv():
    """Check mailboxes for multiple users from a CSV file."""
    print('\nCSV must have a header row and contain one extension per row')
    print('Field: extension')
    input_file = input('Enter CSV file name or full path: ') or 'mailboxes.csv'

    try:
        with open(input_file, 'r', encoding='utf8') as my_file:
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
        logger.error(f'CSV file not found: {input_file}')
        print(f'Error: CSV file not found: {input_file}')


def main():
    """Menu to choose single user or CSV list."""
    while True:
        input_type_csv = input('Use CSV?: (y/n) ') or 'n'
        if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
            use_csv()
            break
        else:
            single_user()
            break


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    basepath = Path.cwd()

    config_file = input('CUC JSON File (cuc-info.json): ') or 'cuc-info.json'
    if not config_file.endswith('.json'):
        config_file = config_file + '.json'
    config = load_server_config(basepath / config_file)

    cuc_server = config.get('server')
    username = config.get('username')
    password = config.get('password')
    version = config.get('version', '15.0')

    logger = setup_logger(basepath / 'logs' / (log_filename_prefix + cuc_server + '-' + time.strftime("%Y_%m_%d-%H_%M_%S") + '.log'))

    if password == '' or password is None:
        password = getpass.getpass(f'Enter CUC Password for {username}: ')

    logger.info(f'Starting check_userMailbox for server: {cuc_server} (version: {version})')
    extension_field = get_extension_field(version)
    logger.info(f'Using field: {extension_field} for extension lookup')

    http_session = requests.Session()
    http_session.auth = HTTPBasicAuth(username, password)
    http_session.headers.update({'Content-Type': 'application/json'})

    main()

    logger.info('Script completed')
