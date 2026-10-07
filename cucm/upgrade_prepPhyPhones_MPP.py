#!/usr/bin/env python3
# TITLE: Phones Prep for MPP Upgrade

"""
Prepare Physical Phones for Migration to Webex Calling
Sets the Phone Load on each phone based on its model (14.4(1) loads for the 78xx
and 88xx series), sets the Load Server to cloudupgrader.webex.com and disables
Peer Firmware Sharing, then resets the phone so the changes are applied immediately.
Phones whose model has no load mapping are logged and skipped.

Phone identifiers can be a device name (SEP0123456789AB) or a MAC address in any
common format (0123456789AB, 01:23:45:67:89:ab, 0123.4567.89ab). A MAC address is
looked up as SEP<MAC>.

Supports a single phone or a CSV file of phones on a single CUCM cluster.

CSV Format (file name only, read from the _DATA folder; default: phone.csv, header row required):
  phone
  SEP0123456789AB
  (the column may also be named mac, device or name; a 12-digit MAC gets the SEP prefix)

Arguments:
  --debug   Enable debug-level console logging (default: info level)
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import argparse
import csv
import re
import urllib3
from lxml import etree
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL

CSV_COLUMNS = ('phone', 'mac', 'device', 'name')
LOAD_SERVER_ADDRESS = 'cloudupgrader.webex.com'


def format_phone_identifier(identifier):
    """Return the device name for a device name or MAC address (adds SEP prefix to a MAC)"""
    identifier = identifier.strip()
    stripped = re.sub(r'[:.\-]', '', identifier)
    if re.fullmatch(r'[0-9A-Fa-f]{12}', stripped):
        return 'SEP' + stripped.upper()
    return identifier


def get_phone_load_for_model(model):
    """Return the Phone Load for a phone model, or None if the model is not mapped"""
    if not model:
        return None

    if '7832' in model:
        return 'sip7832.14-4-1-0001-36'
    elif '8832' in model:
        return 'sip8832.14-4-1-0001-36'
    elif '8845' in model or '8865' in model:
        return 'sip8845_65.14-4-1-0001-36'
    elif '88' in model:
        return 'sip88xx.14-4-1-0001-36'
    elif '78' in model:
        return 'sip78xx.14-4-1-0001-36'

    return None


def read_identifiers_from_csv(csv_path, logger):
    """Read phone identifiers from the CSV file"""
    if not Path(csv_path).exists():
        logger.error('CSV file not found: %s', csv_path)
        print(f"Error: CSV file not found: {csv_path}")
        return []

    identifiers = []
    with open(csv_path, 'r', newline='', encoding='utf8') as f:
        reader = csv.DictReader(f)
        fields = {(h or '').strip().lower(): h for h in (reader.fieldnames or [])}
        column = next((fields[c] for c in CSV_COLUMNS if c in fields), None)
        if not column:
            print(f"Error: CSV must have one of these columns: {', '.join(CSV_COLUMNS)}")
            logger.error('CSV missing phone column')
            return []
        for row in reader:
            value = (row.get(column) or '').strip()
            if value:
                identifiers.append(value)
    logger.info('Read %d phone identifiers from %s', len(identifiers), csv_path)
    return identifiers


def prep_phone(phone_identifier, axl, logger):
    """Set Phone Load, Load Server and Peer Firmware Sharing on a phone and reset it. Returns True on success"""
    name = format_phone_identifier(phone_identifier)
    logger.info('Preparing phone for MPP migration: %s', name)

    phone = axl.get_Phone(name=name)
    if not phone.get('success'):
        print(f"  ✗ {name} - not found")
        logger.error('Phone %s not found: %s', name, phone.get('error'))
        return False

    model = (phone.get('response') or {}).get('model') or ''
    logger.info('Phone model: %s', model)

    phone_load = get_phone_load_for_model(model)
    if not phone_load:
        print(f"  ✗ {name} - no Phone Load mapping for model {model}")
        logger.warning('No Phone Load mapping for model: %s', model)
        return False

    logger.info('Setting Phone Load: %s', phone_load)
    logger.info('Setting Load Server to: %s', LOAD_SERVER_ADDRESS)
    logger.info('Disabling Peer Firmware Sharing')

    vendor_config = etree.Element('vendorConfig')
    etree.SubElement(vendor_config, 'loadServer').text = LOAD_SERVER_ADDRESS
    etree.SubElement(vendor_config, 'peerFirmwareSharing').text = '0'

    result = axl.update_Phone(name=name, loadInformation=phone_load, vendorConfig=vendor_config)
    if not result.get('success'):
        print(f"  ✗ {name} - update failed: {result.get('error')}")
        logger.error('Phone configuration update failed for %s: %s', name, result.get('error'))
        return False

    reset = axl.reset_Phone(name=name)
    if not reset.get('success'):
        print(f"  ✗ {name} - updated but reset failed: {reset.get('error')}")
        logger.error('Phone reset failed for %s: %s', name, reset.get('error'))
        return False

    print(f"  ✓ {name} ({model}) load {phone_load}, reset")
    logger.info('Phone %s updated and reset', name)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare physical phones for Webex Calling migration')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-upgrade-prepPhyPhones-MPP.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Prep Phones For MPP Upgrade - Started")

    print("="*80)
    print("Prepare Physical Phones for Migration to Webex Calling")
    print("="*80)

    cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
    if not cluster:
        print("Error: Unable to load cluster information")
        sys.exit(1)

    username, password = load_credentials('CUCM', cluster['name'])

    server = cluster['server']
    version = cluster['version']
    wsdl = (script_dir / 'schema' / version / 'AXLAPI.wsdl').absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

    if prompt_yes_no('\nPrepare phones from CSV file?', default=False):
        csv_name = input('Enter CSV file name in _DATA folder [phone.csv]: ').strip() or 'phone.csv'
        data_dir = script_dir.parent / '_DATA'
        csv_file = str(data_dir / Path(csv_name).name)
        logger.info("Using CSV file: %s", csv_file)
        identifiers = read_identifiers_from_csv(csv_file, logger)
    else:
        value = input('Enter phone device name or MAC address: ').strip()
        identifiers = [value] if value else []

    if not identifiers:
        print("No phones to process")
        logger.info("Prep Phones For MPP Upgrade - Completed")
        sys.exit(0)

    if not prompt_yes_no(f'\nUpdate and reset {len(identifiers)} phone(s) on {cluster["name"]}?', default=False):
        print("Update cancelled by user")
        logger.info("Update cancelled by user")
        logger.info("Prep Phones For MPP Upgrade - Completed")
        sys.exit(0)

    print()
    succeeded = sum(1 for identifier in identifiers if prep_phone(identifier, axl, logger))
    failed = len(identifiers) - succeeded

    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"Phones processed:  {len(identifiers)}")
    print(f"Phones updated:    {succeeded}")
    print(f"Phones failed:     {failed}")
    print(f"{'='*80}\n")
    logger.info('Summary - processed: %d, updated: %d, failed: %d', len(identifiers), succeeded, failed)

    logger.info("Prep Phones For MPP Upgrade - Completed")
