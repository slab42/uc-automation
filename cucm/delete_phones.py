#!/usr/bin/env python3
# TITLE: Phones Delete And Orphan DNs

"""
Delete Phones and their Orphaned Directory Numbers
Looks up each phone by device name or MAC address, records the directory numbers
(number and partition) on the phone, deletes the phone, then checks whether each
directory number is still assigned to any other device, device profile or remote
destination profile. Directory numbers no longer assigned are deleted. Directory
numbers that are still in use, or that cannot be deleted because of another
dependency (hunt line group, call pickup, etc.), are logged and listed in the summary.

Phone identifiers can be a device name (SEPDC0539FB8FA2, CSFjsmith) or a MAC address
in any common format (DC0539FB8FA2, dc:05:39:fb:8f:a2, dc05.39fb.8fa2). A MAC address
is looked up as SEP<MAC>.

Supports a single phone or a CSV file of phones on a single CUCM cluster.

CSV Format (file name only, read from the _DATA folder; default: delete_phones.csv, header row required):
  device
  SEPDC0539FB8FA2
  AC7A5941C3B0
  CSFjsmith
  (the column may also be named mac, name or phone)

Deletion Order: Phone -> Directory Numbers with no remaining device

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
from setup.prompt_utils import prompt_yes_no, prompt_delete_mode
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL

CSV_COLUMNS = ('device', 'mac', 'name', 'phone')


def candidate_names(identifier):
    """Return device names to try for a device name or MAC address"""
    identifier = identifier.strip()
    names = [identifier]
    stripped = re.sub(r'[:.\-]', '', identifier)
    if re.fullmatch(r'[0-9A-Fa-f]{12}', stripped):
        names.append('SEP' + stripped.upper())
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def read_identifiers_from_csv(csv_path, logger):
    """Read phone identifiers from the CSV file"""
    if not Path(csv_path).exists():
        logger.error('CSV file not found: %s', csv_path)
        print(f"Error: CSV file not found: {csv_path}")
        return []

    identifiers = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fields = {(h or '').strip().lower(): h for h in (reader.fieldnames or [])}
        column = next((fields[c] for c in CSV_COLUMNS if c in fields), None)
        if not column:
            print(f"Error: CSV must have one of these columns: {', '.join(CSV_COLUMNS)}")
            logger.error('CSV missing device column')
            return []
        for row in reader:
            value = (row.get(column) or '').strip()
            if value:
                identifiers.append(value)
    logger.info('Read %d phone identifiers from %s', len(identifiers), csv_path)
    return identifiers


def find_phone(identifier, axl, logger):
    """Find a phone and its lines. Returns {'name', 'lines': [(dn, partition)]} or None"""
    for name in candidate_names(identifier):
        result = axl.find_phone_lines(name)
        if not result.get('success'):
            logger.error('Phone lookup failed for %s: %s', name, result.get('error'))
            continue
        rows = result.get('response', [])
        if not rows:
            continue
        lines = []
        for row in rows:
            if row['pattern'] and (row['pattern'], row['partition']) not in lines:
                lines.append((row['pattern'], row['partition']))
        return {'name': rows[0]['name'], 'lines': lines}
    return None


def fmt_dn(pattern, partition):
    return f"{pattern} (partition: {partition or '<None>'})"


def find_phones(identifiers, axl, logger):
    """Look up all identifiers. Returns (phones found, identifiers not found)"""
    phones = []
    not_found = []
    seen = set()
    for identifier in identifiers:
        phone = find_phone(identifier, axl, logger)
        if not phone:
            logger.warning('Phone not found: %s', identifier)
            not_found.append(identifier)
            continue
        if phone['name'] in seen:
            continue
        seen.add(phone['name'])
        logger.info('Found phone %s with lines: %s', phone['name'],
                    ', '.join(fmt_dn(p, pt) for p, pt in phone['lines']) or 'none')
        phones.append(phone)
    return phones, not_found


def print_phones_available(phones, not_found):
    """List the phones available for deletion and any identifiers not found"""
    print(f"\n{'='*80}")
    print(f"Phones Available for Deletion ({len(phones)} found)")
    print(f"{'='*80}\n")
    for phone in phones:
        print(f"Phone: {phone['name']}")
        for pattern, partition in phone['lines']:
            print(f"  Line: {fmt_dn(pattern, partition)}")
        if not phone['lines']:
            print("  Line: none")
    if not_found:
        print(f"\nNot found ({len(not_found)}):")
        for identifier in not_found:
            print(f"  - {identifier}")
    print(f"\n{'='*80}")


def delete_phones(phones, axl, logger, individual=False):
    """Delete the phones. Returns (deleted phones, failed count)"""
    deleted = []
    failed = 0
    print("\nDeleting phones...\n")
    for phone in phones:
        name = phone['name']
        if individual and not prompt_yes_no(f"Delete Phone '{name}'?", default=False):
            print(f"  - Skipped Phone: {name}")
            logger.info('Skipped Phone: %s', name)
            continue
        try:
            result = axl.remove_Phone(name)
        except Exception as e:
            result = {'success': False, 'error': str(e)}
        if result.get('success'):
            print(f"  ✓ Phone: {name}")
            logger.info('Deleted phone: %s', name)
            deleted.append(phone)
        else:
            print(f"  ✗ Phone: {name} - {result.get('error')}")
            logger.error('Failed to delete phone %s: %s', name, result.get('error'))
            failed += 1
    return deleted, failed


def cleanup_directory_numbers(deleted_phones, axl, logger):
    """Delete DNs from deleted phones that are no longer on any device.
    Returns (deleted, still_in_use, undeletable) lists of (pattern, partition, detail)"""
    dns = []
    for phone in deleted_phones:
        for dn in phone['lines']:
            if dn not in dns:
                dns.append(dn)

    deleted, in_use, undeletable = [], [], []
    if not dns:
        return deleted, in_use, undeletable

    print("\nChecking directory numbers...\n")
    for pattern, partition in dns:
        label = fmt_dn(pattern, partition)
        result = axl.find_line_devices(pattern, partition)
        if not result.get('success'):
            print(f"  ✗ {label} - device check failed: {result.get('error')}")
            logger.error('Device check failed for %s: %s', label, result.get('error'))
            undeletable.append((pattern, partition, f"device check failed: {result.get('error')}"))
            continue

        devices = result.get('response', [])
        if devices:
            print(f"  - {label} still assigned to: {', '.join(devices)}")
            logger.info('DN %s still assigned to %s, not deleted', label, ', '.join(devices))
            in_use.append((pattern, partition, ', '.join(devices)))
            continue

        result = axl.remove_Line(pattern, partition or None)
        if result.get('success'):
            print(f"  ✓ Deleted DN: {label}")
            logger.info('Deleted DN: %s', label)
            deleted.append((pattern, partition, ''))
        else:
            error = result.get('error')
            print(f"  ✗ Could not delete DN: {label} - {error}")
            logger.error('Could not delete DN %s due to dependency: %s', label, error)
            undeletable.append((pattern, partition, error))

    return deleted, in_use, undeletable


def print_summary(phones_found, phones_deleted, phones_failed, dn_deleted, dn_in_use, dn_undeletable, logger):
    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"Phones found:             {phones_found}")
    print(f"Phones deleted:           {phones_deleted}")
    print(f"Phones failed:            {phones_failed}")
    print(f"DNs deleted:              {len(dn_deleted)}")
    print(f"DNs still on a device:    {len(dn_in_use)}")
    print(f"DNs unable to delete:     {len(dn_undeletable)}")
    logger.info('Summary - phones found: %d, deleted: %d, failed: %d; DNs deleted: %d, still in use: %d, unable to delete: %d',
                phones_found, phones_deleted, phones_failed, len(dn_deleted), len(dn_in_use), len(dn_undeletable))

    if dn_undeletable:
        print("\nDirectory numbers unable to delete (dependency):")
        for pattern, partition, error in dn_undeletable:
            print(f"  - {fmt_dn(pattern, partition)}: {error}")
            logger.warning('Unable to delete DN %s: %s', fmt_dn(pattern, partition), error)
    print(f"{'='*80}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Delete phones and their orphaned directory numbers')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-delete-phones.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Delete Phones And Orphan DNs - Started")

    print("="*80)
    print("Delete Phones and Orphaned Directory Numbers")
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

    if prompt_yes_no('\nDelete phones from CSV file?', default=False):
        csv_name = input('Enter CSV file name in _DATA folder [delete_phones.csv]: ').strip() or 'delete_phones.csv'
        data_dir = script_dir.parent / '_DATA'
        csv_file = str(data_dir / Path(csv_name).name)
        logger.info("Using CSV file: %s", csv_file)
        identifiers = read_identifiers_from_csv(csv_file, logger)
    else:
        value = input('Enter phone device name or MAC address: ').strip()
        identifiers = [value] if value else []

    if not identifiers:
        print("No phones to process")
        logger.info("Delete Phones And Orphan DNs - Completed")
        sys.exit(0)

    print(f"\nLooking up {len(identifiers)} phone(s) on {cluster['name']}...\n")
    phones, not_found = find_phones(identifiers, axl, logger)
    print_phones_available(phones, not_found)

    if not phones:
        print("\nNo matching phones found")
        logger.info("Delete Phones And Orphan DNs - Completed")
        sys.exit(0)

    mode = prompt_delete_mode(f'\nDelete {len(phones)} phone(s) and any directory numbers left unassigned?')
    if mode == 'n':
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        logger.info("Delete Phones And Orphan DNs - Completed")
        sys.exit(0)

    deleted_phones, phones_failed = delete_phones(phones, axl, logger, individual=(mode == 'i'))
    dn_deleted, dn_in_use, dn_undeletable = cleanup_directory_numbers(deleted_phones, axl, logger)

    print_summary(len(phones), len(deleted_phones), phones_failed, dn_deleted, dn_in_use, dn_undeletable, logger)

    logger.info("Delete Phones And Orphan DNs - Completed")
