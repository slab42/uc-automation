#!/usr/bin/env python3

"""
List Cisco Unity Connection Call Handlers to CSV.

Query all Call Handlers from CUC and export displayName and extension to CSV.

Usage:
    python3 list_CallHandlers.py

The script is interactive and will prompt for:
    CUC Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    CSV Output File (callhandlers.csv): path to save the output CSV file.

CSV Output Format:
displayName,extension,objectId
Call Handler Name,2000,ca8cdbd5-9b1b-4893-9237-171d78b5c6a2
Another Handler,2001,f349f979-308b-4fad-b110-f58c132c2cae

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import time
import requests
from requests.auth import HTTPBasicAuth
import urllib3
from lxml import etree
import csv
from setup.logger import setup_logger
from setup.multi_object_loader import get_object_for_single_operation, load_credentials

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


def main(http_session, cuc_server, logger):
    """Main operation logic."""
    csv_file = input('CSV Output File (callhandlers.csv): ').strip() or 'callhandlers.csv'

    try:
        handlers = get_call_handlers(http_session, cuc_server)
        write_to_csv(handlers, csv_file)

        logger.info('Call Handlers export completed successfully')

    except Exception as e:
        logger.error(f'Script failed: {e}')
        sys.exit(1)


if __name__ == '__main__':
    basepath = Path.cwd()

    # Load cluster information from clusters.csv or interactive input
    cluster = get_object_for_single_operation(basepath, 'CUC')
    if not cluster:
        print("Error: Unable to load cluster information")
        sys.exit(1)

    # Load credentials
    username, password = load_credentials('CUC', cluster['name'])

    cuc_server = cluster['server']

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-list-callhandlers-{cuc_server}.log"
    logger = setup_logger(log_file)
    logger.info("List Call Handlers - Started")

    http_session = requests.Session()
    http_session.auth = HTTPBasicAuth(username, password)
    http_session.headers.update({'Content-Type': 'application/xml'})

    main(http_session, cuc_server, logger)

    logger.info('Script completed')
