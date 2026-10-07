#!/usr/bin/env python3
# TITLE: Delete CTI Route Points And DNs

"""
Delete CTI Route Points and their Orphaned Directory Numbers
Looks up each CTI Route Point by device name or by directory number, records the
directory numbers (number and partition) on the CTI Route Point, deletes the CTI Route
Point, then checks whether each directory number is still assigned to any other device,
device profile or remote destination profile. Directory numbers no longer assigned are
deleted. Directory numbers that are still in use, or that cannot be deleted because of
another dependency (hunt pilot, call pickup, etc.), are logged and listed in the summary.

Each identifier is matched exactly against CTI Route Point names and against the
directory numbers on CTI Route Points. A directory number that exists on more than one
CTI Route Point (for example in different partitions) selects all of them.

Supports a single CTI Route Point or a CSV file on a single CUCM cluster.

CSV Format (file name only, read from the _DATA folder; default: delete_ctiRP.csv, header row required):
  device
  CTIRP_MainAA
  +14155551234
  5001
  (the column may also be named name, ctirp, dn, number or pattern)

Deletion Order: CTI Route Point -> Directory Numbers with no remaining device

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
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL

CSV_COLUMNS = ('device', 'name', 'ctirp', 'dn', 'number', 'pattern')


def read_identifiers_from_csv(csv_path, logger):
    """Read CTI Route Point names or directory numbers from the CSV file"""
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
    logger.info('Read %d identifiers from %s', len(identifiers), csv_path)
    return identifiers


def fmt_dn(pattern, partition):
    return f"{pattern} (partition: {partition or '<None>'})"


def find_route_points(identifier, axl, logger):
    """Find CTI Route Points by name or DN. Returns list of {'name', 'lines': [(dn, partition)]}"""
    result = axl.find_cti_route_point_lines(identifier)
    if not result.get('success'):
        logger.error('CTI Route Point lookup failed for %s: %s', identifier, result.get('error'))
        return []

    route_points = {}
    for row in result.get('response', []):
        rp = route_points.setdefault(row['name'], {'name': row['name'], 'lines': []})
        if row['pattern'] and (row['pattern'], row['partition']) not in rp['lines']:
            rp['lines'].append((row['pattern'], row['partition']))
    return list(route_points.values())


def find_all_route_points(identifiers, axl, logger):
    """Look up all identifiers. Returns (route points found, identifiers not found)"""
    found = []
    not_found = []
    seen = set()
    for identifier in identifiers:
        matches = find_route_points(identifier, axl, logger)
        if not matches:
            logger.warning('CTI Route Point not found: %s', identifier)
            not_found.append(identifier)
            continue
        for rp in matches:
            if rp['name'] in seen:
                continue
            seen.add(rp['name'])
            logger.info('Found CTI Route Point %s (matched %s) with lines: %s', rp['name'], identifier,
                        ', '.join(fmt_dn(p, pt) for p, pt in rp['lines']) or 'none')
            found.append(rp)
    return found, not_found


def print_available(route_points, not_found):
    """List the CTI Route Points available for deletion and any identifiers not found"""
    print(f"\n{'='*80}")
    print(f"CTI Route Points Available for Deletion ({len(route_points)} found)")
    print(f"{'='*80}\n")
    for rp in route_points:
        print(f"CTI Route Point: {rp['name']}")
        for pattern, partition in rp['lines']:
            print(f"  Line: {fmt_dn(pattern, partition)}")
        if not rp['lines']:
            print("  Line: none")
    if not_found:
        print(f"\nNot found ({len(not_found)}):")
        for identifier in not_found:
            print(f"  - {identifier}")
    print(f"\n{'='*80}")


def delete_route_points(route_points, axl, logger):
    """Delete the CTI Route Points. Returns (deleted, failed count)"""
    deleted = []
    failed = 0
    print("\nDeleting CTI Route Points...\n")
    for rp in route_points:
        name = rp['name']
        try:
            result = axl.remove_Cti_Route_Point(name)
        except Exception as e:
            result = {'success': False, 'error': str(e)}
        if result.get('success'):
            print(f"  ✓ CTI Route Point: {name}")
            logger.info('Deleted CTI Route Point: %s', name)
            deleted.append(rp)
        else:
            print(f"  ✗ CTI Route Point: {name} - {result.get('error')}")
            logger.error('Failed to delete CTI Route Point %s: %s', name, result.get('error'))
            failed += 1
    return deleted, failed


def cleanup_directory_numbers(deleted_rps, axl, logger):
    """Delete DNs from deleted CTI Route Points that are no longer on any device.
    Returns (deleted, still_in_use, undeletable) lists of (pattern, partition, detail)"""
    dns = []
    for rp in deleted_rps:
        for dn in rp['lines']:
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


def print_summary(found, rps_deleted, rps_failed, dn_deleted, dn_in_use, dn_undeletable, logger):
    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"CTI Route Points found:   {found}")
    print(f"CTI Route Points deleted: {rps_deleted}")
    print(f"CTI Route Points failed:  {rps_failed}")
    print(f"DNs deleted:              {len(dn_deleted)}")
    print(f"DNs still on a device:    {len(dn_in_use)}")
    print(f"DNs unable to delete:     {len(dn_undeletable)}")
    logger.info('Summary - CTI Route Points found: %d, deleted: %d, failed: %d; DNs deleted: %d, still in use: %d, unable to delete: %d',
                found, rps_deleted, rps_failed, len(dn_deleted), len(dn_in_use), len(dn_undeletable))

    if dn_undeletable:
        print("\nDirectory numbers unable to delete (dependency):")
        for pattern, partition, error in dn_undeletable:
            print(f"  - {fmt_dn(pattern, partition)}: {error}")
            logger.warning('Unable to delete DN %s: %s', fmt_dn(pattern, partition), error)
    print(f"{'='*80}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Delete CTI Route Points and their orphaned directory numbers')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-delete-ctiRP.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Delete CTI Route Points And DNs - Started")

    print("="*80)
    print("Delete CTI Route Points and Orphaned Directory Numbers")
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

    if prompt_yes_no('\nDelete CTI Route Points from CSV file?', default=False):
        csv_name = input('Enter CSV file name in _DATA folder [delete_ctiRP.csv]: ').strip() or 'delete_ctiRP.csv'
        data_dir = script_dir.parent / '_DATA'
        csv_file = str(data_dir / Path(csv_name).name)
        logger.info("Using CSV file: %s", csv_file)
        identifiers = read_identifiers_from_csv(csv_file, logger)
    else:
        value = input('Enter CTI Route Point name or directory number: ').strip()
        identifiers = [value] if value else []

    if not identifiers:
        print("No CTI Route Points to process")
        logger.info("Delete CTI Route Points And DNs - Completed")
        sys.exit(0)

    print(f"\nLooking up {len(identifiers)} identifier(s) on {cluster['name']}...\n")
    route_points, not_found = find_all_route_points(identifiers, axl, logger)
    print_available(route_points, not_found)

    if not route_points:
        print("\nNo matching CTI Route Points found")
        logger.info("Delete CTI Route Points And DNs - Completed")
        sys.exit(0)

    if not prompt_yes_no(f'\nDelete {len(route_points)} CTI Route Point(s) and any directory numbers left unassigned?', default=False):
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        logger.info("Delete CTI Route Points And DNs - Completed")
        sys.exit(0)

    deleted_rps, rps_failed = delete_route_points(route_points, axl, logger)
    dn_deleted, dn_in_use, dn_undeletable = cleanup_directory_numbers(deleted_rps, axl, logger)

    print_summary(len(route_points), len(deleted_rps), rps_failed, dn_deleted, dn_in_use, dn_undeletable, logger)

    logger.info("Delete CTI Route Points And DNs - Completed")
