#!/usr/bin/env python3
# TITLE: Phones Migrate To MPP Load

"""
Migrate Physical Phones to MPP Firmware
Sets the Phone Load on each phone based on its model (MPP 12.0(7) loads for the
78xx and 88xx series) and resets the phone so the change is applied immediately.
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
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL

CSV_COLUMNS = ('phone', 'mac', 'device', 'name')


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
        return 'sip7832.12-0-7MPP0501-123'
    elif '8832' in model:
        return 'sip8832.12-0-7MPP0501-123'
    elif '8845' in model or '8865' in model:
        return 'sip8845_65.12-0-7MPP0201-66'
    elif '88' in model:
        return 'sip88xx.12-0-7MPP0501-123'
    elif '78' in model:
        return 'sip78xx.12-0-7MPP0501-123'

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


def migrate_phone(phone_identifier, axl, logger):
    """Set the MPP Phone Load on a phone and reset it. Returns True on success"""
    name = format_phone_identifier(phone_identifier)
    logger.info('Migrating phone: %s', name)

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
    result = axl.update_Phone(name=name, loadInformation=phone_load)
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
    parser = argparse.ArgumentParser(description='Set the MPP Phone Load on physical phones and reset them')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-migrate-PhyPhones-MPP.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Migrate Phones To MPP Load - Started")

    print("="*80)
    print("Migrate Physical Phones to MPP Firmware")
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

    if prompt_yes_no('\nMigrate phones from CSV file?', default=False):
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
        logger.info("Migrate Phones To MPP Load - Completed")
        sys.exit(0)

    if not prompt_yes_no(f'\nSet MPP Phone Load and reset {len(identifiers)} phone(s) on {cluster["name"]}?', default=False):
        print("Migration cancelled by user")
        logger.info("Migration cancelled by user")
        logger.info("Migrate Phones To MPP Load - Completed")
        sys.exit(0)

    print()
    succeeded = sum(1 for identifier in identifiers if migrate_phone(identifier, axl, logger))
    failed = len(identifiers) - succeeded

    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"Phones processed:  {len(identifiers)}")
    print(f"Phones migrated:   {succeeded}")
    print(f"Phones failed:     {failed}")
    print(f"{'='*80}\n")
    logger.info('Summary - processed: %d, migrated: %d, failed: %d', len(identifiers), succeeded, failed)

    logger.info("Migrate Phones To MPP Load - Completed")
