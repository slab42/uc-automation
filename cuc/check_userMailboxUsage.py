#!/usr/bin/env python3

"""
Export user mailbox usage from Cisco Unity Connection in CSV format.

Query users by extension and export mailbox size data in CSV format:
dtmfAccessID, alias, mailboxSize

Usage:
    python3 check_userMailboxUsage.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use CSV?: (y/n): choose 'y' to export mailbox usage for multiple users from a CSV file,
        or 'n' (default) to check a single user's mailbox.

    If 'n' (single user):
        Extension: the extension number to look up

    If 'y' (CSV):
        Enter CSV file name or full path: path to the CSV file
            (default: mailboxes.csv)
        Output file name (default: mailbox_usage_report.csv): path to output CSV file

CSV Input Format:
extension
2001
2002

CSV Output Format:
dtmfAccessID,alias,mailboxSize
2001,user1,123.45
2002,user2,456.78

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader, writer
import time
import requests
import urllib3
from requests.auth import HTTPBasicAuth
from datetime import datetime
from lxml import etree
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials

log_filename_prefix = 'check-userMailboxUsage-'


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


def get_user_mailbox_usage(http_session, cuc_server, extension, version):
    """
    Query a user by extension and retrieve mailbox size.

    Args:
        http_session: Requests session with auth configured
        cuc_server (string): CUC server address
        extension (string): Extension number to look up
        version (string): CUC version to determine field to query

    Returns:
        dict: Result with keys 'success', 'dtmfAccessId', 'alias', 'mailboxSize', 'error'
    """
    try:
        base_url = f'https://{cuc_server}/vmrest'
        extension_field = get_extension_field(version)

        logger.info(f'Querying mailbox usage for {extension_field}: {extension}')

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
            return {'success': False, 'dtmfAccessId': extension, 'alias': '', 'mailboxSize': '', 'error': f'No user found'}

        user_alias = matched_user.get('Alias', 'N/A')
        user_dtmf = matched_user.get('DtmfAccessId', extension)
        user_uri = matched_user.get('URI', '')

        if not user_uri:
            logger.error(f'No URI found for extension {extension}')
            return {'success': False, 'dtmfAccessId': user_dtmf, 'alias': user_alias, 'mailboxSize': '', 'error': 'No URI found'}

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
        current_size_mb = round(current_size_bytes / (1024 * 1024), 2)

        logger.info(f'Retrieved mailbox usage for {user_alias} ({user_dtmf}): {current_size_bytes} bytes, {current_size_mb} MB')
        return {'success': True, 'dtmfAccessId': user_dtmf, 'alias': user_alias, 'mailboxSize': current_size_mb, 'error': ''}

    except requests.exceptions.RequestException as e:
        error_msg = f'API request failed: {str(e)}'
        logger.error(error_msg)
        return {'success': False, 'dtmfAccessId': extension, 'alias': '', 'mailboxSize': '', 'error': error_msg}
    except (KeyError, ValueError) as e:
        error_msg = f'Error parsing response: {str(e)}'
        logger.error(error_msg)
        return {'success': False, 'dtmfAccessId': extension, 'alias': '', 'mailboxSize': '', 'error': error_msg}


def single_user():
    """Export mailbox usage for a single user by extension."""
    extension = input('Extension: ')
    result = get_user_mailbox_usage(http_session, cuc_server, extension, version)
    if result.get('success'):
        print(f"{result['dtmfAccessId']},{result['alias']},{result['mailboxSize']}")
    else:
        logger.error(f"Error for extension {extension}: {result.get('error')}")


def use_csv():
    """Export mailbox usage for multiple users from a CSV file."""
    print('\nCSV must have a header row and contain one extension per row')
    print('Field: extension')
    input_file = input('Enter CSV file name or full path: ') or 'mailboxes.csv'
    output_file = input('Output file name (default: mailbox_usage_report.csv): ') or 'mailbox_usage_report.csv'

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
                        result = get_user_mailbox_usage(http_session, cuc_server, extension, version)
                        if result.get('success'):
                            output_rows.append([result['dtmfAccessId'], result['alias'], result['mailboxSize']])
                        else:
                            logger.warning(f"Skipped extension {extension}: {result.get('error')}")

        with open(output_file, 'w', encoding='utf8', newline='') as out_file:
            csv_writer = writer(out_file)
            csv_writer.writerow(['dtmfAccessID', 'alias', 'mailboxSize'])
            csv_writer.writerows(output_rows)

        logger.info(f'Processed {row_count} users from CSV')
        logger.info(f'Exported {len(output_rows)} users to {output_file}')
        print(f'\nExported {len(output_rows)} users to {output_file}')

    except FileNotFoundError:
        logger.error(f'CSV file not found: {input_file}')
        print(f'Error: CSV file not found: {input_file}')
    except IOError as e:
        logger.error(f'Error writing to output file: {str(e)}')
        print(f'Error writing to output file: {str(e)}')


def main():
    """Menu to choose single user or CSV list."""
    while True:
        use_csv_mode = prompt_yes_no('Use CSV?', default=False)
        if use_csv_mode:
            use_csv()
            break
        else:
            single_user()
            break


if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    basepath = Path.cwd()

    # Load cluster information from clusters.csv or interactive input
    cluster = get_object_for_single_operation(basepath, 'CUC', server_type='publisher')
    if not cluster:
        print("Error: Unable to load cluster information")
        sys.exit(1)

    # Load credentials from credentials.env
    username, password = load_credentials('CUC', cluster['name'])

    cuc_server = cluster['server']
    version = cluster['version']

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-check-usermailboxusage-{cuc_server}.log"
    logger = setup_logger(log_file)
    logger.info("Check User Mailbox Usage - Started")

    logger.info(f'Starting check_userMailboxUsage for server: {cuc_server} (version: {version})')
    extension_field = get_extension_field(version)
    logger.info(f'Using field: {extension_field} for extension lookup')

    http_session = requests.Session()
    http_session.auth = HTTPBasicAuth(username, password)
    http_session.headers.update({'Content-Type': 'application/json'})

    main()

    logger.info('Script completed')
