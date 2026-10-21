#!/usr/bin/env python3
# TITLE: Adv Pattern and RP Update Description

"""
Rename the department portion of the descriptions on an Advertised Pattern and its
matching Route Pattern, individually or from a list in CSV

CSV Format (file name only, read from the _DATA folder; default: AdvP_RP_updateDesc.csv, header row required):
  pattern, departmentName
  +155585944XX,Sales

departmentName (column 2) is the NEW department name. If not supplied via --dept and not
present in the CSV, the script will prompt for it during execution.

Workflow:
  1. Choose single or CSV mode, then select the cluster(s) to apply the changes to.
  2. The current descriptions are read and only the text before the fixed suffix is replaced:
       Advertised Pattern: <dept> Webex Calling <10 digits>
       Route Pattern:      <dept> DID to Webex Calling
  3. A description that does not follow those formats is left unchanged and a warning is logged.

10 digit numbers are automatically prefixed with +1 for the Advertised Pattern and
\\+1 for the Route Pattern.

Arguments:
  --dept    New department name to use for descriptions
  --debug   Enable debug-level console logging (default: info level)

Logs: ../_logs/<timestamp>-AdvP-RP-updateDesc.log
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
from setup.prompt_utils import prompt_yes_no, prompt_use_multiple
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from ucmAPI import AXL

ROUTE_PARTITION = 'Enterprise_PT'

ADVP_DESC_SUFFIX = re.compile(r'^(.*?)( Webex Calling\b.*)$')
RP_DESC_SUFFIX = re.compile(r'^(.*?)( DID to Webex Calling\b.*)$')

DEFAULT_CSV = 'AdvP_RP_updateDesc.csv'


def get_department_name(dept_state, csv_value=''):
    """Determine departmentName using precedence: --dept argument, CSV column, prompt"""
    if dept_state.get('dept'):
        return dept_state['dept']
    if csv_value:
        return csv_value
    if not dept_state.get('prompted'):
        print('Name entered will be used for all entries.  If you plan on more than 1 department name, add departmentName column to CSV and start over. (Example: HFS)')
        while not dept_state.get('prompted'):
            dept_state['prompted'] = input('New Department Name: ').strip()
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


def replace_dept(description, dept, suffix_regex):
    """Return the description with the department portion replaced, or None if the format is not recognized"""
    match = suffix_regex.match(description or '')
    if not match:
        return None
    return f"{dept}{match.group(2)}"


def update_advertised_pattern(axl, logger, pattern, dept):
    """Update the department in the Advertised Pattern description"""
    formatted = format_advertised_pattern(pattern)
    current = axl.get_advertised_pattern(formatted)
    if not current.get('success'):
        logger.error('Advertised Pattern %s: %s', formatted, current.get('error'))
        return current
    old_desc = (current['response'] or {}).get('description') or ''
    new_desc = replace_dept(old_desc, dept, ADVP_DESC_SUFFIX)
    if new_desc is None:
        logger.warning('Advertised Pattern %s: description "%s" not in expected format, unchanged', formatted, old_desc)
        return {'success': False, 'response': '', 'error': 'Unexpected description format'}
    if new_desc == old_desc:
        logger.info('Advertised Pattern %s: description already "%s"', formatted, old_desc)
        return {'success': True, 'response': 'No change', 'error': ''}
    logger.info('Updating Advertised Pattern %s: "%s" -> "%s"', formatted, old_desc, new_desc)
    result = axl.update_advertised_pattern(formatted, new_desc)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))
    return result


def update_route_pattern(axl, logger, pattern, dept):
    """Update the department in the Route Pattern description"""
    formatted = format_route_pattern(pattern)
    current = axl.get_Route_Pattern(formatted, ROUTE_PARTITION)
    if not current.get('success'):
        logger.error('Route Pattern %s: %s', formatted, current.get('error'))
        return current
    old_desc = (current['response'] or {}).get('description') or ''
    new_desc = replace_dept(old_desc, dept, RP_DESC_SUFFIX)
    if new_desc is None:
        logger.warning('Route Pattern %s: description "%s" not in expected format, unchanged', formatted, old_desc)
        return {'success': False, 'response': '', 'error': 'Unexpected description format'}
    if new_desc == old_desc:
        logger.info('Route Pattern %s: description already "%s"', formatted, old_desc)
        return {'success': True, 'response': 'No change', 'error': ''}
    logger.info('Updating Route Pattern %s: "%s" -> "%s"', formatted, old_desc, new_desc)
    result = axl.update_Route_Pattern(formatted, ROUTE_PARTITION, new_desc)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))
    return result


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
    """Update the Advertised Pattern and Route Pattern descriptions for each entry"""
    for pattern, dept in entries:
        update_advertised_pattern(axl, logger, pattern, dept)
        update_route_pattern(axl, logger, pattern, dept)


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
    parser = argparse.ArgumentParser(description='Update Advertised Pattern and Route Pattern department descriptions in CUCM')
    parser.add_argument('--dept', dest='dept', default=None, help='New department name to use for descriptions')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-AdvP-RP-updateDesc.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Advertised Pattern and RP Update Description - Started")

    dept_state = {'dept': args.dept, 'prompted': None}

    operation_params = prompt_operation(script_dir)
    entries = collect_entries(operation_params, dept_state)
    if not entries:
        sys.exit(1 if entries is None else 0)

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
        username, password = load_credentials('CUCM', target['name'])
        axl = build_axl(script_dir, target['server'], target['version'], username, password)
        run_operation(axl, logger, entries)

    logger.info("Advertised Pattern and RP Update Description - Completed")
