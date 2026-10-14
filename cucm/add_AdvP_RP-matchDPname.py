#!/usr/bin/env python3
# TITLE: Adv Pattern and RP Add - DeptMatch

"""
Add Advertised Pattern and matching Route Pattern individually or from a list in CSV

CSV Format (file name only, read from the _DATA folder; default: add_AdvP_RP.csv, header row required):
  pattern, departmentName
  +155585944XX,Sales

departmentName (column 2) is optional. If not supplied via --dept and not present in
the CSV, the script will prompt for it during execution.

Workflow:
  1. Select the source cluster; all Device Pool names are read from it.
  2. The department is the text before the first dash in each Device Pool name
     (example: Sales-HQ -> Sales). Matching is case-insensitive.
  3. Choose single or CSV mode, then select the cluster(s) to apply the changes to.
  4. Entries whose department matches no Device Pool are NOT created. They are saved to
     _DATA/<timestamp>-AdvP_RP_dept_mismatch.csv (pattern, departmentName).

10 digit numbers are automatically prefixed with +1 for the Advertised Pattern and
\\+1 for the Route Pattern.

Arguments:
  --dept    Department name to use for descriptions
  --debug   Enable debug-level console logging (default: info level)

Logs: ../_logs/<timestamp>-add-AdvP-RP-matchDPname.log
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
from setup.prompt_utils import prompt_yes_no, prompt_use_multiple
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from ucmAPI import AXL

PATTERN_TYPE = 'Enterprise Number'
HOSTED_ROUTE_PSTN_RULE = 'No PSTN'
PSTN_FAIL_STRIP = '0'
PSTN_FAIL_PREPEND = ''

ROUTE_PARTITION = 'Enterprise_PT'
GATEWAY_ROUTE_LIST = 'WebexCalling'

DEFAULT_CSV = 'add_AdvP_RP.csv'


def get_department_name(dept_state, csv_value=''):
    """Determine departmentName using precedence: --dept argument, CSV column, prompt"""
    if dept_state.get('dept'):
        return dept_state['dept']
    if csv_value:
        return csv_value
    if not dept_state.get('prompted'):
        print('Name entered will be used for all entries.  If you plan on more than 1 department name, add departmentName column to CSV and start over. (Example: HFS)')
        while not dept_state.get('prompted'):
            dept_state['prompted'] = input('Department Name: ').strip()
    return dept_state['prompted']


def format_advertised_pattern(pattern):
    """Format a number for the Advertised Pattern.
    10 digit numbers get a +1 prefix. 11 digit numbers starting with 1 get a + prefix."""
    value = pattern.strip()
    if value.isdigit() and len(value) == 10:
        return '+1' + value
    if value.isdigit() and len(value) == 11 and value.startswith('1'):
        return '+' + value
    return value


def format_route_pattern(pattern):
    """Format a number for the Route Pattern. Numbers already in +1 format get a
    \\ prefix. 10 digit numbers get a \\+1 prefix. 11 digit numbers starting
    with 1 get a \\+ prefix."""
    value = pattern.strip()
    if value.startswith('+1'):
        return '\\' + value
    if value.isdigit() and len(value) == 10:
        return '\\+1' + value
    if value.isdigit() and len(value) == 11 and value.startswith('1'):
        return '\\+' + value
    return value


def add_advertised_pattern(axl, logger, pattern, dept):
    """Add an Advertised Pattern for the given number"""
    formatted = format_advertised_pattern(pattern)
    description = f"{dept} Webex Calling {formatted[-10:]}"
    logger.info('Adding Advertised Pattern: %s as %s', formatted, PATTERN_TYPE)
    result = axl.add_advertised_patterns(description=description,
                                         pattern=formatted,
                                         patternType=PATTERN_TYPE,
                                         hostedRoutePSTNRule=HOSTED_ROUTE_PSTN_RULE,
                                         pstnFailStrip=PSTN_FAIL_STRIP,
                                         pstnFailPrepend=PSTN_FAIL_PREPEND)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))
    return result


def add_route_pattern(axl, logger, pattern, dept):
    """Add a Route Pattern for the given number"""
    formatted = format_route_pattern(pattern)
    description = f"{dept} DID to Webex Calling"
    logger.info('Adding Route Pattern: %s in partition %s', formatted, ROUTE_PARTITION)
    result = axl.add_Route_Pattern(pattern=formatted,
                                   description=description,
                                   routePartitionName=ROUTE_PARTITION,
                                   gatewayRouteList=GATEWAY_ROUTE_LIST)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))
    return result


def add_pattern_pair(axl, logger, pattern, dept):
    """Add the Advertised Pattern and matching Route Pattern"""
    add_advertised_pattern(axl, logger, pattern, dept)
    add_route_pattern(axl, logger, pattern, dept)


def get_device_pool_departments(axl, logger):
    """Return a dict of lowercase department -> department, from the text before the first dash of each Device Pool name"""
    result = axl.list_DevicePools()
    if not result.get('success'):
        logger.error('Unable to list Device Pools: %s', result.get('error'))
        return None
    departments = {}
    for pool in result.get('response') or []:
        name = (pool.get('name') or '').strip()
        if '-' not in name:
            continue
        dept = name.split('-', 1)[0].strip()
        if dept:
            departments.setdefault(dept.lower(), dept)
    return departments


def collect_entries(operation_params, dept_state):
    """Build the list of (pattern, department) entries from single input or CSV"""
    entries = []
    if operation_params['type'] == 'csv':
        csv_file_path = operation_params['csv_file']
        if not Path(csv_file_path).exists():
            print(f"Error: CSV file not found: {csv_file_path}")
            return None
        with open(csv_file_path, 'r', encoding='utf8', newline='') as my_file:
            csv_reader = csv.reader(my_file)
            next(csv_reader, None)
            for row in csv_reader:
                if not row or not row[0].strip():
                    continue
                csv_dept = row[1].strip() if len(row) > 1 else ''
                entries.append((row[0].strip(), get_department_name(dept_state, csv_dept)))
    else:
        pattern = input('Pattern (Number): ').strip()
        if not pattern:
            print('No pattern provided')
            return []
        entries.append((pattern, get_department_name(dept_state)))
    return entries


def split_entries(entries, departments):
    """Split entries into (matched, mismatched) based on the Device Pool department names"""
    matched = []
    mismatched = []
    for pattern, dept in entries:
        if dept.lower() in departments:
            matched.append((pattern, departments[dept.lower()]))
        else:
            mismatched.append((pattern, dept))
    return matched, mismatched


def save_mismatches(mismatched, logger):
    """Write entries with no matching Device Pool department to a CSV in _DATA"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_file = Path(__file__).parent.parent / '_DATA' / f"{timestamp}-AdvP_RP_dept_mismatch.csv"
    with open(out_file, 'w', encoding='utf8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['pattern', 'departmentName'])
        writer.writerows(mismatched)
    logger.warning('%d entries skipped, no matching Device Pool department. Saved to %s', len(mismatched), out_file)
    print(f"{len(mismatched)} entries skipped (no matching Device Pool department). Saved to: {out_file}")


def prompt_operation(script_dir):
    """Prompt for single or CSV mode. Returns operation params dict"""
    use_csv = prompt_yes_no('Use CSV?', default=False)
    if not use_csv:
        return {'type': 'single'}
    print('\nCSV Must have header row')
    print('Field Order: pattern, departmentName (departmentName is optional)')
    csv_name = input(f'Enter CSV file name in _DATA folder [{DEFAULT_CSV}]: ').strip() or DEFAULT_CSV
    csv_file = str(script_dir.parent / '_DATA' / Path(csv_name).name)
    return {'type': 'csv', 'csv_file': csv_file}


def run_operation(axl, logger, entries):
    """Add the Advertised Pattern and Route Pattern for each entry"""
    for pattern, dept in entries:
        add_pattern_pair(axl, logger, pattern, dept)


def build_axl(script_dir, server, version, username, password):
    """Create an AXL client for the cluster"""
    wsdl = (script_dir / 'schema' / version / 'AXLAPI.wsdl').absolute().as_uri()
    return AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)


def run_operation_on_cluster(script_dir, cluster_data, entries, cluster_credentials, logger):
    """Run the operation on a single cluster"""
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        username, password = cluster_credentials[cluster_name]
        axl = build_axl(script_dir, server, cluster_data['version'], username, password)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        run_operation(axl, logger, entries)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error('Exception on cluster %s: %s', cluster_name, e)
        print(f"✗ Failed on {cluster_name}: {e}")
        return False


def run_on_all_clusters(script_dir, clusters_data, entries, logger):
    """Run the operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("=" * 80)
    print("Loading Credentials")
    print("=" * 80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)
    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    for cluster in clusters_data:
        if run_operation_on_cluster(script_dir, cluster, entries, cluster_credentials, logger):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Advertised Pattern and Route Pattern in CUCM')
    parser.add_argument('--dept', dest='dept', default=None, help='Department name to use for descriptions')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-add-AdvP-RP-matchDPname.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Advertised Pattern and RP Add - Started")

    dept_state = {'dept': args.dept, 'prompted': None}

    # Select the source cluster and read the Device Pool department names
    print('\nSelect the cluster to read Device Pool names from')
    source = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
    if not source:
        print("Error: Unable to load cluster information")
        sys.exit(1)
    source_user, source_pass = load_credentials('CUCM', source['name'])
    source_axl = build_axl(script_dir, source['server'], source['version'], source_user, source_pass)
    departments = get_device_pool_departments(source_axl, logger)
    if not departments:
        print(f"Error: no department Device Pools found on {source['name']}")
        sys.exit(1)
    logger.info('Departments from %s Device Pools: %s', source['name'], ', '.join(sorted(departments.values())))
    print(f"Found {len(departments)} departments in Device Pools on {source['name']}")

    operation_params = prompt_operation(script_dir)
    entries = collect_entries(operation_params, dept_state)
    if not entries:
        sys.exit(1 if entries is None else 0)
    entries, mismatched = split_entries(entries, departments)
    if mismatched:
        save_mismatches(mismatched, logger)
    if not entries:
        print('No entries matched a Device Pool department. Nothing to apply.')
        logger.info("Advertised Pattern and RP Add - Completed")
        sys.exit(0)

    # Select the cluster(s) to apply the changes to
    print('\nSelect the cluster to apply changes to')
    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data and prompt_use_multiple(len(clusters_data), 'clusters', default=False):
        run_on_all_clusters(script_dir, clusters_data, entries, logger)
    else:
        target = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not target:
            print("Error: Unable to load cluster information")
            sys.exit(1)
        if target['name'] == source['name']:
            axl = source_axl
        else:
            username, password = load_credentials('CUCM', target['name'])
            axl = build_axl(script_dir, target['server'], target['version'], username, password)
        run_operation(axl, logger, entries)

    logger.info("Advertised Pattern and RP Add - Completed")
