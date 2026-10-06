#!/usr/bin/env python3
# TITLE: Export Hunt Groups By Number

"""
Export only the Hunt Pilots, Hunt Lists and Line Groups that contain specific numbers

Reads a CSV list of numbers. A Hunt Pilot is exported when its pilot pattern is one
of the numbers, or when a Line Group in its Hunt List has one of the numbers as a
member. Line Groups are limited to those containing a listed number; if the Hunt Pilot
itself matched, all of its Line Groups are exported. Numbers are compared ignoring a
leading '+'.

Output layout is identical to export_hunt_groups.py. One CSV is written per cluster
to _DATA/reports/ with the cluster name and a timestamp in the filename.

Supports single or multiple CUCM clusters

Input CSV Format (default: _DATA/huntgroup_numbers.csv, header row required):
number
5551001
5551002

Arguments:
  --debug   Enable debug-level console logging (default: info level)
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import csv
from datetime import datetime
import argparse
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL
from export_hunt_groups import write_csv, _sort_key


def _norm(number):
    return str(number or '').strip().lstrip('+')


def read_numbers_from_csv(csv_path, logger):
    """Read the numbers from the first column (or a 'number' column) of the CSV"""
    if not Path(csv_path).exists():
        logger.error('CSV file not found: %s', csv_path)
        print(f"Error: CSV file not found: {csv_path}")
        return set()

    numbers = set()
    with open(csv_path, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader, [])
        col = 0
        for i, name in enumerate(header):
            if name.strip().lower() in ('number', 'dn', 'pattern'):
                col = i
                break
        for row in reader:
            if len(row) > col and row[col].strip():
                numbers.add(_norm(row[col]))

    logger.info('Read %d numbers from %s', len(numbers), csv_path)
    return numbers


def collect_hunt_rows(axl, numbers, logger):
    """Build export rows (dicts with a 'members' list) for Hunt Pilots matching the numbers"""
    rows = []

    hp_result = axl.list_hunt_pilots()
    if not hp_result.get('success'):
        logger.error('Failed to fetch Hunt Pilots: %s', hp_result.get('error'))
        print(f"Error: {hp_result.get('error')}")
        return rows

    hunt_pilots = sorted(hp_result.get('response', []), key=lambda h: h.get('pattern') or '')
    logger.info('Found %d Hunt Pilots, filtering on %d numbers', len(hunt_pilots), len(numbers))

    hl_cache = {}
    lg_cache = {}
    matched_numbers = set()

    for hp in hunt_pilots:
        pattern = hp.get('pattern')
        detail_result = axl.get_hunt_pilot_details(hp.get('uuid'))
        if not detail_result.get('success'):
            logger.error('get_hunt_pilot_details failed for %s: %s', pattern, detail_result.get('error'))
            print(f"  ✗ {pattern}: {detail_result.get('error')}")
            continue
        d = detail_result['response']

        pilot_match = _norm(d['pattern']) in numbers
        if pilot_match:
            matched_numbers.add(_norm(d['pattern']))

        hl_name = d['huntListName']
        line_groups = []
        if hl_name:
            if hl_name not in hl_cache:
                hl_result = axl.get_hunt_list(hl_name)
                if not hl_result.get('success'):
                    logger.error('get_hunt_list failed for %s: %s', hl_name, hl_result.get('error'))
                hl_cache[hl_name] = hl_result.get('response', {}) if hl_result.get('success') else {}
            hl_members = sorted(hl_cache[hl_name].get('members', []), key=_sort_key)

            for hl_member in hl_members:
                lg_name = hl_member.get('line_group')
                if not lg_name:
                    continue
                if lg_name not in lg_cache:
                    lg_result = axl.get_line_group(lg_name)
                    if not lg_result.get('success'):
                        logger.error('get_line_group failed for %s: %s', lg_name, lg_result.get('error'))
                    lg_cache[lg_name] = lg_result.get('response', {}) if lg_result.get('success') else {}
                lg_members = sorted(lg_cache[lg_name].get('members', []), key=_sort_key)
                dns = [m['dn'] for m in lg_members]
                hits = {_norm(dn) for dn in dns} & numbers
                matched_numbers |= hits
                if pilot_match or hits:
                    line_groups.append((lg_name, dns))

        if not pilot_match and not line_groups:
            continue

        base = {
            'Pilot': d['pattern'],
            'Partition': hp.get('routePartitionName') or '',
            'Description': d['description'],
            'Alerting Name': d['alertingName'],
            'ForwardNoAnswer': d['forwardHuntNoAnswer'],
            'ForwardBusy': d['forwardHuntBusy'],
            'QueueCalls': 'Yes' if d['queueEnabled'] else 'No',
            'MaxNumberInQueue': d['maxCallersInQueue'] if d['queueEnabled'] else '',
            'WhenIsFull': d['queueFullDestination'] if d['queueEnabled'] else '',
            'MaxWaitTime': d['maxWaitTimeInQueue'] if d['queueEnabled'] else '',
            'WhenMaxWaitIsMet': d['maxWaitTimeDestination'] if d['queueEnabled'] else '',
            'NoHuntMembers': d['noAgentDestination'] if d['queueEnabled'] else '',
            'HuntList': hl_name,
        }

        logger.info('Hunt Pilot %s matched: Hunt List %s, %d Line Groups', pattern, hl_name or 'None', len(line_groups))

        if not line_groups:
            rows.append({**base, 'LineGroup': '', 'members': []})
            continue

        for i, (lg_name, members) in enumerate(line_groups):
            if i == 0:
                rows.append({**base, 'LineGroup': lg_name, 'members': members})
            else:
                rows.append({'Pilot': base['Pilot'], 'HuntList': hl_name, 'LineGroup': lg_name, 'members': members})

    missing = sorted(numbers - matched_numbers)
    if missing:
        logger.warning('Numbers not found in any Hunt Pilot or Line Group: %s', ', '.join(missing))
        print(f"  Not found: {', '.join(missing)}")

    return rows


def export_cluster(cluster, username, password, numbers, script_dir, reports_dir, logger):
    """Connect to one cluster and export the matching hunt groups"""
    cluster_name = cluster['name']
    server = cluster['server']
    version = cluster['version']

    wsdl = (script_dir / 'schema' / version / 'AXLAPI.wsdl').absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

    logger.info('Processing cluster: %s (%s)', cluster_name, server)
    print(f"\nExporting matching Hunt Groups from {cluster_name} ({server})...")
    rows = collect_hunt_rows(axl, numbers, logger)
    return write_csv(rows, cluster_name, reports_dir, logger)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export Hunt Pilots, Hunt Lists and Line Groups containing listed numbers')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    reports_dir = script_dir.parent / '_DATA' / 'reports'
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-export-huntgroups-byNumber.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Export Hunt Groups By Number - Started")

    print("="*80)
    print("Export Hunt Pilots, Hunt Lists, and Line Groups By Number")
    print("="*80)

    csv_file = input('Enter CSV file name or full path [_DATA/huntgroup_numbers.csv]: ').strip() or str(script_dir.parent / '_DATA' / 'huntgroup_numbers.csv')
    logger.info("Using CSV file: %s", csv_file)
    numbers = read_numbers_from_csv(csv_file, logger)
    if not numbers:
        print("Error: No numbers to search for")
        sys.exit(1)

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    use_multiple = bool(clusters_data) and prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

    if use_multiple:
        use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)
        cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)
        successful = failed = 0
        for cluster in clusters_data:
            try:
                username, password = cluster_credentials[cluster['name']]
                export_cluster(cluster, username, password, numbers, script_dir, reports_dir, logger)
                successful += 1
            except Exception as e:
                logger.error('Failed to process cluster %s: %s', cluster['name'], str(e))
                print(f"✗ Failed on {cluster['name']}: {str(e)}")
                failed += 1
        print(f"\nCompleted: {successful} successful, {failed} failed")
    else:
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)
        username, password = load_credentials('CUCM', cluster['name'])
        export_cluster(cluster, username, password, numbers, script_dir, reports_dir, logger)

    logger.info("Export Hunt Groups By Number - Completed")
