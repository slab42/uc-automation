#!/usr/bin/env python3

"""
List Cisco Unity Connection Call Handlers to CSV.

Query all Call Handlers from CUC and export displayName and extension to CSV.

Usage:
    python3 list_CallHandlers.py

The script is interactive and will prompt for:
    CUC JSON File (cuc-info.json): path to the JSON file with server/login
        info (default: cuc-info.json). If the password field in that file
        is blank, you will be prompted to enter it.
    CSV Output File (callhandlers.csv): path to save the output CSV file.

CSV Output Format:
displayName,extension,objectId
Call Handler Name,2000,ca8cdbd5-9b1b-4893-9237-171d78b5c6a2
Another Handler,2001,f349f979-308b-4fad-b110-f58c132c2cae

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import getpass
import logging
from logging.handlers import StreamHandler
import time
import requests
from requests.auth import HTTPBasicAuth
import urllib3
from lxml import etree
import csv
from setup.on_prem.logger import setup_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log_filename_prefix = 'list-CallHandlers-'

# Call Handlers to skip in export
SKIP_HANDLERS = {
    'Opening Greeting',
    'Operator',
    'Goodbye',
    'undeliverablemessagesmailbox',
    'operator'
}


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


def prompt_for_password(prompt_text='Password: '):
    """Prompt user for password without echoing to screen."""
    return getpass.getpass(prompt_text)


def get_call_handlers(http_session, cuc_server):
    """
    Query all Call Handlers from CUC.

    Args:
        http_session: Requests session with auth configured
        cuc_server (string): CUC server address

    Returns:
        list: List of dicts with keys 'displayName', 'extension', 'uri'
    """
    try:
        base_url = f'https://{cuc_server}/vmrest'
        handlers_url = f'{base_url}/handlers/callhandlers/'

        logger.info(f'Retrieving Call Handlers from {cuc_server}')

        response = http_session.get(handlers_url, verify=False)
        response.raise_for_status()

        root = etree.fromstring(response.content)
        handler_elements = root.findall('.//Callhandler')

        handlers = []
        for handler_elem in handler_elements:
            handler_dict = {}
            for child in handler_elem:
                handler_dict[child.tag] = child.text

            display_name = handler_dict.get('DisplayName', '')
            extension = handler_dict.get('DtmfAccessId', '')

            is_user_handler = bool(handler_dict.get('RecipientSubscriberObjectId'))

            if display_name not in SKIP_HANDLERS and not is_user_handler:
                handlers.append({
                    'displayName': display_name or '',
                    'extension': extension or '',
                    'objectId': handler_dict.get('ObjectId', '')
                })

        logger.info(f'Found {len(handlers)} Call Handlers')
        return handlers

    except requests.exceptions.RequestException as e:
        logger.error(f'Error retrieving Call Handlers: {e}')
        raise
    except etree.XMLSyntaxError as e:
        logger.error(f'Error parsing XML response: {e}')
        raise


def write_to_csv(handlers, csv_file):
    """
    Write Call Handlers to CSV file.

    Args:
        handlers (list): List of handler dicts with displayName, extension, and objectId
        csv_file (str): Path to output CSV file
    """
    try:
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['displayName', 'extension', 'objectId'])
            writer.writeheader()
            writer.writerows(handlers)

        logger.info(f'Exported {len(handlers)} Call Handlers to {csv_file}')
        print(f'\nSuccessfully exported Call Handlers to: {csv_file}')
    except IOError as e:
        logger.error(f'Error writing to CSV file: {e}')
        raise


def main():
    config_file = input('CUC JSON File (cuc-info.json): ').strip() or 'cuc-info.json'

    if not Path(config_file).exists():
        print(f'Error: Config file {config_file} not found')
        sys.exit(1)

    config = load_server_config(config_file)
    cuc_server = config.get('server')
    username = config.get('username')
    password = config.get('password', '')

    if not password:
        password = prompt_for_password('CUC Password: ')

    global logger
    basepath = Path(__file__).parent
    log_path = basepath / 'logs' / (log_filename_prefix + cuc_server + '-' + time.strftime("%Y_%m_%d-%H_%M_%S") + '.log')
    try:
        logger = setup_logger(log_path)
    except (OSError, PermissionError) as e:
        print(f'Warning: Could not write logs to {log_path.parent}')
        print(f'Using stdout-only logging: {e}\n')
        logger = logging.getLogger('cuc_logger')
        logger.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler(sys.stdout)
        message_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
        stdout_handler.setFormatter(message_format)
        logger.addHandler(stdout_handler)

    csv_file = input('CSV Output File (callhandlers.csv): ').strip() or 'callhandlers.csv'

    try:
        http_session = requests.Session()
        http_session.auth = HTTPBasicAuth(username, password)
        http_session.headers.update({'Content-Type': 'application/xml'})

        handlers = get_call_handlers(http_session, cuc_server)
        write_to_csv(handlers, csv_file)

        logger.info('Call Handlers export completed successfully')

    except Exception as e:
        logger.error(f'Script failed: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
