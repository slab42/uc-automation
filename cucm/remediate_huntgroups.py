#!/usr/bin/env python3
# TITLE: Hunt Groups Remediate Unused

"""
Remediate Unused Hunt Pilots, Hunt Lists and Line Groups
Identifies and optionally deletes unused Hunt Pilots by finding empty Line Groups,
then checking if their Hunt Lists have no other dependencies. Also checks all
Hunt Lists directly for ones with no Line Group members, and finds Hunt Pilots
with no Hunt List assigned. If Hunt Lists are safe to delete, their associated
Hunt Pilots are also available for deletion.

Can also delete specific Hunt Pilots from a CSV file and all their related objects
(Hunt Lists and Line Groups), regardless of whether they have members.

CSV Format (default: _DATA/huntPilots.csv):
  pattern,partition
  3150,default
  4000,Marketing
  5555,

Deletion Order: Line Groups -> Hunt Lists -> Hunt Pilots

Supports single or multiple CUCM clusters

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
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no, prompt_use_multiple, prompt_delete_mode
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


def find_hunt_pilots_from_csv(csv_path, axl, logger):
    """Find Hunt Pilots and their related objects from a CSV file"""
    import csv

    unused_objects = {
        'line_groups': [],
        'hunt_lists': [],
        'hunt_pilots': []
    }

    if not Path(csv_path).exists():
        logger.error('CSV file not found: %s', csv_path)
        print(f"Error: CSV file not found: {csv_path}")
        return unused_objects

    print(f"\nReading Hunt Pilot patterns from: {csv_path}\n")

    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or 'pattern' not in reader.fieldnames:
                print("Error: CSV must have 'pattern' column, and optionally 'partition' column")
                logger.error('CSV missing pattern column')
                return unused_objects

            for row in reader:
                pattern = row.get('pattern', '').strip()
                partition = row.get('partition', '').strip() or None

                if not pattern:
                    continue

                logger.info('Processing Hunt Pilot: %s (partition: %s)', pattern, partition or 'any')
                print(f"Hunt Pilot: {pattern}")
                if partition:
                    print(f"  Partition: {partition}")

                hp_result = axl.get_hunt_pilot(pattern, partition)
                if not hp_result.get('success'):
                    logger.warning('Hunt Pilot not found: %s (partition: %s)', pattern, partition or 'any')
                    print(f"  Status: NOT FOUND")
                    print()
                    continue

                hp = hp_result.get('response', {})
                hp_uuid = hp.get('uuid')
                hp_hunt_list = hp.get('huntListName', '')

                logger.info('Found Hunt Pilot: %s (%s)', pattern, hp_uuid)
                print(f"  Hunt List: {hp_hunt_list if hp_hunt_list else 'None'}")

                unused_objects['hunt_pilots'].append({
                    'name': pattern,
                    'uuid': hp_uuid,
                    'hunt_list': hp_hunt_list if hp_hunt_list else 'None'
                })

                if hp_hunt_list:
                    logger.info('Fetching Hunt List: %s', hp_hunt_list)
                    hl_result = axl.get_hunt_list(hp_hunt_list)
                    if hl_result.get('success'):
                        hl = hl_result.get('response', {})
                        hl_uuid = hl.get('uuid')
                        hl_members = hl.get('members', [])

                        unused_objects['hunt_lists'].append({
                            'name': hp_hunt_list,
                            'uuid': hl_uuid,
                            'line_group': 'N/A'
                        })

                        for member in hl_members:
                            lg_name = member.get('line_group')
                            if lg_name:
                                logger.info('Fetching Line Group: %s', lg_name)
                                lg_result = axl.get_line_group(lg_name)
                                if lg_result.get('success'):
                                    lg = lg_result.get('response', {})
                                    lg_uuid = lg.get('uuid')
                                    lg_member_count = lg.get('member_count', 0)

                                    print(f"  Line Group: {lg_name} ({lg_member_count} members)")

                                    unused_objects['line_groups'].append({
                                        'name': lg_name,
                                        'uuid': lg_uuid,
                                        'hunt_lists': [{
                                            'name': hp_hunt_list,
                                            'pkid': hl_uuid,
                                            'hunt_pilots': []
                                        }]
                                    })

                print()

    except Exception as e:
        logger.error('Error reading CSV file: %s', str(e))
        print(f"Error reading CSV file: {str(e)}")

    return unused_objects


def find_hunt_pilots_with_no_hunt_list(axl, logger):
    """Find Hunt Pilots with no Hunt List assigned"""
    found = {
        'hunt_pilots': []
    }

    logger.info('Fetching all Hunt Pilots...')
    hp_result = axl.list_hunt_pilots()

    if not hp_result.get('success'):
        logger.error('Failed to fetch Hunt Pilots: %s', hp_result.get('error'))
        print(f"Error: {hp_result.get('error')}")
        return found

    hunt_pilots = hp_result.get('response', [])
    if not hunt_pilots:
        logger.info('No Hunt Pilots found')
        print("No Hunt Pilots found")
        return found

    logger.info('Found %d Hunt Pilots', len(hunt_pilots))
    if hunt_pilots:
        logger.debug('Sample Hunt Pilot: %s', hunt_pilots[0])

    print(f"\n{'='*80}")
    print(f"Hunt Pilots with no Hunt List assigned")
    print(f"{'='*80}\n")

    for hp in hunt_pilots:
        pattern = hp.get('pattern')
        hunt_list = hp.get('huntListName')
        if not hunt_list:
            hunt_list = ''
        if hunt_list and hunt_list.strip():
            continue

        uuid = hp.get('uuid')
        logger.info('Processing Hunt Pilot with no Hunt List: %s (%s)', pattern, uuid)
        print(f"Hunt Pilot: {pattern}")
        print(f"  Status: SAFE TO DELETE (no Hunt List assigned)")

        found['hunt_pilots'].append({
            'name': pattern,
            'uuid': uuid,
            'hunt_list': 'None'
        })

        print()

    return found


def find_empty_hunt_lists(axl, logger, seen_hunt_lists):
    """Find Hunt Lists with no Line Group members and their Hunt Pilots"""
    found = {
        'hunt_lists': [],
        'hunt_pilots': []
    }

    logger.info('Fetching all Hunt Lists...')
    hl_result = axl.list_hunt_lists()

    if not hl_result.get('success'):
        logger.error('Failed to fetch Hunt Lists: %s', hl_result.get('error'))
        print(f"Error: {hl_result.get('error')}")
        return found

    hunt_lists = hl_result.get('response', [])
    if not hunt_lists:
        logger.info('No Hunt Lists found')
        print("No Hunt Lists found")
        return found

    logger.info('Found %d Hunt Lists', len(hunt_lists))

    print(f"\n{'='*80}")
    print(f"Empty Hunt Lists (no Line Group members)")
    print(f"{'='*80}\n")

    for hl in hunt_lists:
        hl_name = hl.get('name')
        if hl_name in seen_hunt_lists:
            continue

        hl_detail = axl.get_hunt_list(hl_name)
        if not hl_detail.get('success'):
            logger.error('get_hunt_list failed for %s: %s', hl_name, hl_detail.get('error'))
            continue

        detail = hl_detail.get('response', {})
        if detail.get('member_count', 0) != 0:
            continue

        hl_pkid = detail.get('uuid')
        logger.info('Processing empty Hunt List: %s (%s)', hl_name, hl_pkid)
        print(f"Hunt List: {hl_name}")

        hl_deps = axl.find_hunt_list_dependencies(hl_name)
        dependencies = hl_deps.get('response', []) if hl_deps.get('success') else []
        if dependencies:
            logger.info('    Hunt List %s has %d dependencies (not safe to delete)', hl_name, len(dependencies))
            for dep in dependencies:
                dep_name = dep.get('name')
                dep_type = dep.get('type')
                print(f"-> Dependency: {dep_name} ({dep_type})")
                logger.debug('      Dependency: %s (%s)', dep_name, dep_type)
            print(f"  Status: CANNOT DELETE (has other dependencies)")
            print()
            continue

        hp_result = axl.find_hunt_pilots_by_hunt_list(hl_name)
        hunt_pilots = hp_result.get('response', []) if hp_result.get('success') else []
        logger.info('    Found %d Hunt Pilots for Hunt List %s', len(hunt_pilots), hl_name)

        for hp in hunt_pilots:
            print(f"-> Hunt Pilot: {hp.get('name')}")
            logger.info('      Hunt Pilot: %s (%s)', hp.get('name'), hp.get('pkid'))

        print(f"  Status: SAFE TO DELETE")

        found['hunt_lists'].append({
            'name': hl_name,
            'uuid': hl_pkid,
            'line_group': 'None'
        })
        for hp in hunt_pilots:
            found['hunt_pilots'].append({
                'name': hp['name'],
                'uuid': hp.get('pkid'),
                'hunt_list': hl_name
            })

        print()

    return found


def find_unused_hunt_objects(axl, logger):
    """Find Hunt Pilots/Lists/Line Groups that can be deleted"""
    unused_objects = {
        'line_groups': [],
        'hunt_lists': [],
        'hunt_pilots': []
    }

    logger.info('Fetching all Line Groups...')
    lg_result = axl.list_line_groups()

    if not lg_result.get('success'):
        logger.error('Failed to fetch Line Groups: %s', lg_result.get('error'))
        print(f"Error: {lg_result.get('error')}")
        return unused_objects

    line_groups = lg_result.get('response', [])
    if not line_groups:
        logger.info('No Line Groups found')
        print("No Line Groups found")
        return unused_objects

    logger.info('Found %d Line Groups', len(line_groups))

    empty_line_groups = []
    for lg in line_groups:
        lg_detail = axl.get_line_group(lg.get('name'))
        if lg_detail.get('success'):
            detail = lg_detail.get('response', {})
            if detail.get('member_count', 0) == 0:
                empty_line_groups.append(detail)

    logger.info('Found %d empty Line Groups', len(empty_line_groups))

    print(f"\n{'='*80}")
    print(f"Empty Line Groups ({len(empty_line_groups)} found)")
    print(f"{'='*80}\n")

    for lg_detail in empty_line_groups:
        lg_name = lg_detail.get('name')
        lg_uuid = lg_detail.get('uuid')

        logger.info('Processing empty Line Group: %s (%s)', lg_name, lg_uuid)
        print(f"Line Group: {lg_name}")

        hl_result = axl.find_hunt_lists_by_line_group(lg_name)
        if not hl_result.get('success'):
            logger.error('find_hunt_lists_by_line_group failed for %s: %s', lg_name, hl_result.get('error'))
        hunt_lists = hl_result.get('response', []) if hl_result.get('success') else []

        if not hunt_lists:
            print(f"-> No Hunt Lists reference this Line Group")
            unused_objects['line_groups'].append({
                'name': lg_name,
                'uuid': lg_uuid,
                'hunt_lists': []
            })
            print()
            continue

        logger.info('Found %d Hunt Lists for Line Group %s', len(hunt_lists), lg_name)

        safe_to_delete = True
        lg_hunt_lists = []

        for hl in hunt_lists:
            hl_name = hl.get('name')
            hl_pkid = hl.get('pkid')

            logger.info('  Processing Hunt List: %s (%s)', hl_name, hl_pkid)
            print(f"-> Hunt List: {hl_name}")

            hp_result = axl.find_hunt_pilots_by_hunt_list(hl_name)
            hunt_pilots = hp_result.get('response', []) if hp_result.get('success') else []

            logger.info('    Found %d Hunt Pilots for Hunt List %s', len(hunt_pilots), hl_name)

            for hp in hunt_pilots:
                hp_name = hp.get('name')
                hp_pkid = hp.get('pkid')
                print(f"--> Hunt Pilot: {hp_name}")
                logger.info('      Hunt Pilot: %s (%s)', hp_name, hp_pkid)

            hl_deps = axl.find_hunt_list_dependencies(hl_name)
            dependencies = hl_deps.get('response', []) if hl_deps.get('success') else []

            if dependencies:
                logger.info('    Hunt List %s has %d dependencies (not safe to delete)', hl_name, len(dependencies))
                for dep in dependencies:
                    dep_name = dep.get('name')
                    dep_type = dep.get('type')
                    print(f"--> Dependency: {dep_name} ({dep_type})")
                    logger.debug('      Dependency: %s (%s)', dep_name, dep_type)
                safe_to_delete = False
                continue

            lg_hunt_lists.append({
                'name': hl_name,
                'pkid': hl_pkid,
                'hunt_pilots': hunt_pilots
            })

        if safe_to_delete and lg_hunt_lists:
            print(f"  Status: SAFE TO DELETE")
            unused_objects['line_groups'].append({
                'name': lg_name,
                'uuid': lg_uuid,
                'hunt_lists': lg_hunt_lists
            })
            for lg_hl in lg_hunt_lists:
                unused_objects['hunt_lists'].append({
                    'name': lg_hl['name'],
                    'uuid': lg_hl.get('pkid'),
                    'line_group': lg_name
                })
                for hp in lg_hl['hunt_pilots']:
                    unused_objects['hunt_pilots'].append({
                        'name': hp['name'],
                        'uuid': hp.get('pkid'),
                        'hunt_list': lg_hl['name']
                    })
        else:
            print(f"  Status: CANNOT DELETE (has other dependencies)")

        print()

    seen_hunt_lists = {hl['name'] for hl in unused_objects['hunt_lists']}
    empty_hl_found = find_empty_hunt_lists(axl, logger, seen_hunt_lists)
    unused_objects['hunt_lists'].extend(empty_hl_found['hunt_lists'])
    unused_objects['hunt_pilots'].extend(empty_hl_found['hunt_pilots'])

    orphan_hp_found = find_hunt_pilots_with_no_hunt_list(axl, logger)
    unused_objects['hunt_pilots'].extend(orphan_hp_found['hunt_pilots'])

    return unused_objects


def run_operation_on_cluster(cluster_data, cluster_credentials, script_dir, logger):
    """Run the Hunt Pilot analysis on a single cluster"""
    cluster_name = cluster_data.get('name', 'unknown')
    try:
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        unused_objects = find_unused_hunt_objects(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, unused_objects, cluster_name, axl)
    except Exception as e:
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return (False, {'line_groups': [], 'hunt_lists': [], 'hunt_pilots': []}, cluster_name, None)


def run_on_all_clusters(script_dir, clusters_data, logger):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    all_unused_objects = {
        'line_groups': [],
        'hunt_lists': [],
        'hunt_pilots': []
    }
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(cluster, cluster_credentials, script_dir, logger)
        success, unused_objects, cluster_name, axl = result
        if success:
            successful += 1
            for obj_type in ['line_groups', 'hunt_lists', 'hunt_pilots']:
                for obj in unused_objects[obj_type]:
                    obj['cluster'] = cluster_name
                all_unused_objects[obj_type].extend(unused_objects[obj_type])
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_unused_objects, cluster_axl_map


def delete_hunt_objects(unused_objects, cluster_axl_map, logger):
    """Delete Hunt Pilots, Hunt Lists, and Line Groups in order"""
    total_to_delete = (len(unused_objects['hunt_pilots']) +
                       len(unused_objects['hunt_lists']) +
                       len(unused_objects['line_groups']))

    if total_to_delete == 0:
        print("No unused Hunt Pilots, Hunt Lists, or Line Groups to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"Objects Available for Deletion ({total_to_delete} found)")
    print(f"{'='*80}\n")

    if unused_objects['hunt_pilots']:
        print(f"Hunt Pilots ({len(unused_objects['hunt_pilots'])}):")
        for hp in unused_objects['hunt_pilots']:
            cluster = hp.get('cluster', 'Unknown')
            print(f"  - {hp['name']} (Hunt List: {hp['hunt_list']}, Cluster: {cluster})")

    if unused_objects['hunt_lists']:
        print(f"\nHunt Lists ({len(unused_objects['hunt_lists'])}):")
        for hl in unused_objects['hunt_lists']:
            cluster = hl.get('cluster', 'Unknown')
            print(f"  - {hl['name']} (Line Group: {hl['line_group']}, Cluster: {cluster})")

    if unused_objects['line_groups']:
        print(f"\nLine Groups ({len(unused_objects['line_groups'])}):")
        for lg in unused_objects['line_groups']:
            cluster = lg.get('cluster', 'Unknown')
            print(f"  - {lg['name']} (Cluster: {cluster})")

    print(f"\n{'='*80}\n")

    mode = prompt_delete_mode(f'Delete these {total_to_delete} objects?')
    if mode == 'n':
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0
    individual = (mode == 'i')
    logger.info('Delete mode: %s', 'individual' if individual else 'all')

    successful_deletes = 0
    failed_deletes = 0

    print("\nDeleting Hunt Objects (Line Groups first, then Hunt Lists, then Hunt Pilots)...\n")

    for lg in unused_objects['line_groups']:
        cluster_name = lg.get('cluster')
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += 1
            continue

        axl = cluster_axl_map[cluster_name]
        lg_name = lg.get('name')
        if individual and not prompt_yes_no(f"Delete Line Group '{lg_name}'?", default=False):
            print(f"  - Skipped Line Group: {lg_name}")
            logger.info('Skipped Line Group: %s', lg_name)
            continue
        try:
            result = axl.delete_line_group(lg_name)
            if result.get('success'):
                print(f"  ✓ Line Group: {lg_name}")
                logger.info('Deleted Line Group: %s', lg_name)
                successful_deletes += 1
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"  ✗ Line Group: {lg_name} - {error_msg}")
                logger.error('Failed to delete Line Group %s: %s', lg_name, error_msg)
                failed_deletes += 1
        except Exception as e:
            print(f"  ✗ Line Group: {lg_name} - {str(e)}")
            logger.error('Exception deleting Line Group %s: %s', lg_name, str(e))
            failed_deletes += 1

    for hl in unused_objects['hunt_lists']:
        cluster_name = hl.get('cluster')
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += 1
            continue

        axl = cluster_axl_map[cluster_name]
        hl_name = hl.get('name')
        if individual and not prompt_yes_no(f"Delete Hunt List '{hl_name}'?", default=False):
            print(f"  - Skipped Hunt List: {hl_name}")
            logger.info('Skipped Hunt List: %s', hl_name)
            continue
        try:
            result = axl.delete_hunt_list(hl_name)
            if result.get('success'):
                print(f"  ✓ Hunt List: {hl_name}")
                logger.info('Deleted Hunt List: %s', hl_name)
                successful_deletes += 1
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"  ✗ Hunt List: {hl_name} - {error_msg}")
                logger.error('Failed to delete Hunt List %s: %s', hl_name, error_msg)
                failed_deletes += 1
        except Exception as e:
            print(f"  ✗ Hunt List: {hl_name} - {str(e)}")
            logger.error('Exception deleting Hunt List %s: %s', hl_name, str(e))
            failed_deletes += 1

    for hp in unused_objects['hunt_pilots']:
        cluster_name = hp.get('cluster')
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += 1
            continue

        axl = cluster_axl_map[cluster_name]
        hp_name = hp.get('name')
        if individual and not prompt_yes_no(f"Delete Hunt Pilot '{hp_name}'?", default=False):
            print(f"  - Skipped Hunt Pilot: {hp_name}")
            logger.info('Skipped Hunt Pilot: %s', hp_name)
            continue
        hp_uuid = hp.get('uuid')
        try:
            result = axl.delete_hunt_pilot(hp_uuid, hp_name)
            if result.get('success'):
                print(f"  ✓ Hunt Pilot: {hp_name}")
                logger.info('Deleted Hunt Pilot: %s', hp_name)
                successful_deletes += 1
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"  ✗ Hunt Pilot: {hp_name} - {error_msg}")
                logger.error('Failed to delete Hunt Pilot %s: %s', hp_name, error_msg)
                failed_deletes += 1
        except Exception as e:
            print(f"  ✗ Hunt Pilot: {hp_name} - {str(e)}")
            logger.error('Exception deleting Hunt Pilot %s: %s', hp_name, str(e))
            failed_deletes += 1

    return successful_deletes, failed_deletes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remediate Unused Hunt Pilots, Hunt Lists, and Line Groups')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remediate-hunt-pilots.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Unused Hunt Pilots - Started")

    all_unused_objects = {
        'line_groups': [],
        'hunt_lists': [],
        'hunt_pilots': []
    }
    cluster_axl_map = {}

    print("="*80)
    print("Remediate Hunt Pilots, Hunt Lists, and Line Groups")
    print("="*80)
    csv_file = None
    if prompt_yes_no('\nDelete Hunt Pilots from CSV file?', default=False):
        csv_file = input('Enter CSV file name or full path [_DATA/huntPilots.csv]: ').strip() or str(basepath.parent / '_DATA' / 'huntPilots.csv')
        logger.info("Using CSV file for Hunt Pilot deletion: %s", csv_file)

    if csv_file:
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUCM', cluster['name'])

        server = cluster['server']
        version = cluster['version']

        wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        unused_objects = find_hunt_pilots_from_csv(csv_file, axl, logger)
        for obj_type in ['line_groups', 'hunt_lists', 'hunt_pilots']:
            for obj in unused_objects[obj_type]:
                obj['cluster'] = cluster['name']
            all_unused_objects[obj_type].extend(unused_objects[obj_type])
        cluster_axl_map[cluster['name']] = axl
    else:
        clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
        if clusters_data:
            use_multiple = prompt_use_multiple(len(clusters_data), 'clusters', default=False)

            if use_multiple:
                all_unused_objects, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger)
            else:
                cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
                if not cluster:
                    print("Error: Unable to load cluster information")
                    sys.exit(1)

                username, password = load_credentials('CUCM', cluster['name'])

                server = cluster['server']
                version = cluster['version']

                wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
                wsdl = wsdl_dir.absolute().as_uri()
                axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

                unused_objects = find_unused_hunt_objects(axl, logger)
                for obj_type in ['line_groups', 'hunt_lists', 'hunt_pilots']:
                    for obj in unused_objects[obj_type]:
                        obj['cluster'] = cluster['name']
                    all_unused_objects[obj_type].extend(unused_objects[obj_type])
                cluster_axl_map[cluster['name']] = axl

        else:
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUCM', cluster['name'])

            server = cluster['server']
            version = cluster['version']

            wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
            wsdl = wsdl_dir.absolute().as_uri()
            axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

            unused_objects = find_unused_hunt_objects(axl, logger)
            for obj_type in ['line_groups', 'hunt_lists', 'hunt_pilots']:
                for obj in unused_objects[obj_type]:
                    obj['cluster'] = cluster['name']
                all_unused_objects[obj_type].extend(unused_objects[obj_type])
            cluster_axl_map[cluster['name']] = axl

    total_unused = (len(all_unused_objects['hunt_pilots']) +
                    len(all_unused_objects['hunt_lists']) +
                    len(all_unused_objects['line_groups']))

    if total_unused > 0:
        successful, failed = delete_hunt_objects(all_unused_objects, cluster_axl_map, logger)

        print(f"\n{'='*80}")
        print(f"Deletion Summary")
        print(f"{'='*80}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total: {successful + failed}")
        print(f"{'='*80}\n")

        logger.info("Deletion Summary - Successful: %d, Failed: %d, Total: %d", successful, failed, successful + failed)
    else:
        print("\nNo unused Hunt Pilots, Hunt Lists, or Line Groups found")

    logger.info("Remediate Unused Hunt Pilots - Completed")
