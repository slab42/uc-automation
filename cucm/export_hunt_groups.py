#!/usr/bin/env python3
# TITLE: Export Hunt Groups

"""
Export Hunt Pilots, Hunt Lists and Line Groups from CUCM to a CSV file

Connects to CUCM, retrieves all Hunt Pilots with their settings, the Hunt List
each one uses, and the Line Groups (with members) in that Hunt List. A Hunt Pilot
whose Hunt List has more than one Line Group gets one row per Line Group: the first
row carries the Hunt Pilot settings, and the following rows repeat only the Hunt
Pilot, Hunt List and Line Group columns. Every row carries the Line Group's own
settings (RNA reversion timeout, distribution algorithm, and the hunt options for
No Answer, Busy and Not Available).

One CSV is written per cluster to _DATA/reports/ with the cluster name and a
timestamp in the filename.

Supports single or multiple CUCM clusters

CSV Output Format:
Pilot, Partition, Description, Alerting Name, ForwardNoAnswer, ForwardBusy, QueueCalls,
MaxNumberInQueue, WhenIsFull, MaxWaitTime, WhenMaxWaitIsMet, NoHuntMembers, HuntList,
LineGroup, RNA, Distribution, HuntNoAnswer, HuntBusy, HuntNotAvail, LineGroupMember1, LineGroupMember2, ... (as many as the largest Line Group)

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

BASE_HEADERS = ['Pilot', 'Partition', 'Description', 'Alerting Name', 'ForwardNoAnswer', 'ForwardBusy',
                'QueueCalls', 'MaxNumberInQueue', 'WhenIsFull', 'MaxWaitTime', 'WhenMaxWaitIsMet',
                'NoHuntMembers', 'HuntList', 'LineGroup', 'RNA', 'Distribution', 'HuntNoAnswer', 'HuntBusy',
                'HuntNotAvail']


def _sort_key(item):
    """Sort members by their numeric order, keeping unordered ones last"""
    try:
        return int(item.get('order'))
    except (TypeError, ValueError):
        return 10**6


def lg_settings_row(lg):
    """Map a Line Group's settings to the export columns"""
    return {
        'RNA': lg.get('rna_timeout', ''),
        'Distribution': lg.get('distribution', ''),
        'HuntNoAnswer': lg.get('hunt_no_answer', ''),
        'HuntBusy': lg.get('hunt_busy', ''),
        'HuntNotAvail': lg.get('hunt_not_available', ''),
    }


def collect_hunt_rows(axl, logger):
    """Build export rows (dicts with a 'members' list) for every Hunt Pilot"""
    rows = []

    hp_result = axl.list_hunt_pilots()
    if not hp_result.get('success'):
        logger.error('Failed to fetch Hunt Pilots: %s', hp_result.get('error'))
        print(f"Error: {hp_result.get('error')}")
        return rows

    hunt_pilots = sorted(hp_result.get('response', []), key=lambda h: h.get('pattern') or '')
    logger.info('Found %d Hunt Pilots', len(hunt_pilots))

    hl_cache = {}
    lg_cache = {}

    for hp in hunt_pilots:
        pattern = hp.get('pattern')
        detail_result = axl.get_hunt_pilot_details(hp.get('uuid'))
        if not detail_result.get('success'):
            logger.error('get_hunt_pilot_details failed for %s: %s', pattern, detail_result.get('error'))
            print(f"  ✗ {pattern}: {detail_result.get('error')}")
            continue
        d = detail_result['response']

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
                lg_settings = lg_settings_row(lg_cache[lg_name])
                line_groups.append((lg_name, [m['dn'] for m in lg_members], lg_settings))

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

        logger.info('Hunt Pilot %s: Hunt List %s, %d Line Groups', pattern, hl_name or 'None', len(line_groups))

        if not line_groups:
            rows.append({**base, 'LineGroup': '', 'members': []})
            continue

        for i, (lg_name, members, lg_settings) in enumerate(line_groups):
            if i == 0:
                rows.append({**base, 'LineGroup': lg_name, **lg_settings, 'members': members})
            else:
                rows.append({'Pilot': base['Pilot'], 'HuntList': hl_name, 'LineGroup': lg_name, **lg_settings, 'members': members})

    return rows


def write_csv(rows, cluster_name, reports_dir, logger):
    """Write rows to a timestamped CSV in the reports folder"""
    if not rows:
        logger.warning('No Hunt Pilots to export for %s', cluster_name)
        print(f"No Hunt Pilots found on {cluster_name}")
        return None

    max_members = max((len(r['members']) for r in rows), default=0)
    headers = BASE_HEADERS + [f'LineGroupMember{i}' for i in range(1, max_members + 1)]

    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
    output_path = reports_dir / f'hunt_groups-{cluster_name}-{timestamp}.csv'

    with open(output_path, 'w', newline='', encoding='utf8') as f:
        writer = csv.DictWriter(f, fieldnames=headers, restval='')
        writer.writeheader()
        for row in rows:
            out = {k: v for k, v in row.items() if k != 'members'}
            for i, dn in enumerate(row['members'], start=1):
                out[f'LineGroupMember{i}'] = dn
            writer.writerow(out)

    logger.info('Exported %d rows to %s', len(rows), output_path)
    print(f"✓ Exported {len(rows)} rows to {output_path}")
    return output_path


def export_cluster(cluster, username, password, script_dir, reports_dir, logger):
    """Connect to one cluster and export its hunt groups"""
    cluster_name = cluster['name']
    server = cluster['server']
    version = cluster['version']

    wsdl = (script_dir / 'schema' / version / 'AXLAPI.wsdl').absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

    logger.info('Processing cluster: %s (%s)', cluster_name, server)
    print(f"\nExporting Hunt Groups from {cluster_name} ({server})...")
    rows = collect_hunt_rows(axl, logger)
    return write_csv(rows, cluster_name, reports_dir, logger)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export Hunt Pilots, Hunt Lists and Line Groups to CSV')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    reports_dir = script_dir.parent / '_DATA' / 'reports'
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-export-hunt-groups.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Export Hunt Groups - Started")

    print("="*80)
    print("Export Hunt Pilots, Hunt Lists, and Line Groups")
    print("="*80)

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    use_multiple = bool(clusters_data) and prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

    if use_multiple:
        use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)
        cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)
        successful = failed = 0
        for cluster in clusters_data:
            try:
                username, password = cluster_credentials[cluster['name']]
                export_cluster(cluster, username, password, script_dir, reports_dir, logger)
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
        export_cluster(cluster, username, password, script_dir, reports_dir, logger)

    logger.info("Export Hunt Groups - Completed")
