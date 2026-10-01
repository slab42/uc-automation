#!/usr/bin/env python3
# TITLE: Remediate Device Pools

"""
Remediate Device Pools - List Dependencies and Delete Without Dependencies
Lists Device Pools (from a CSV file or a text search) along with their dependency
count (devices, device profiles, remote destination profiles, and Route Groups
whose member devices use the Device Pool), then optionally deletes the Device
Pools that have no dependencies.

CSV Format (default: _DATA/devicePools.csv):
  devicePool
  DP_SiteA_Default
  DP_SiteB_Default
  DP_Unused_Legacy

Supports single or multiple CUCM clusters

Arguments:
  --debug   Enable debug-level console logging (default: info level)
  --listD   List each dependency (name and type) under its Device Pool
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictReader
from datetime import datetime
import argparse
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


def read_device_pool_names_from_csv(csv_path, logger):
    """Read Device Pool names from a CSV file (devicePool column)"""
    names = []

    if not Path(csv_path).exists():
        logger.error('CSV file not found: %s', csv_path)
        print(f"Error: CSV file not found: {csv_path}")
        return names

    print(f"\nReading Device Pool names from: {csv_path}\n")

    try:
        with open(csv_path, 'r', encoding='utf8') as my_file:
            reader = DictReader(my_file)
            if not reader.fieldnames or 'devicePool' not in reader.fieldnames:
                print("Error: CSV must have 'devicePool' column")
                logger.error('CSV missing devicePool column')
                return names

            for row in reader:
                name = row.get('devicePool', '').strip()
                if name:
                    names.append(name)
    except Exception as e:
        logger.error('Error reading CSV file: %s', str(e))
        print(f"Error reading CSV file: {str(e)}")

    return names


def display_device_pools(axl, logger, dp_names=None, search_term=None, list_deps=False):
    """List Device Pools (from dp_names or search_term) with their dependency counts"""
    no_dependency_pools = []

    logger.info('Fetching Device Pools...')
    pools_result = axl.list_device_pools_sql()

    if not pools_result.get('success'):
        logger.error('Failed to fetch Device Pools: %s', pools_result.get('error'))
        print(f"Error: {pools_result.get('error')}")
        return []

    pools = pools_result.get('response')

    if not pools:
        logger.info('No Device Pools found')
        print("No Device Pools found")
        return []

    if dp_names:
        dp_names_lower = {n.lower() for n in dp_names}
        matched = [p for p in pools if p.get('name', '').lower() in dp_names_lower]
        found_names = {p.get('name', '').lower() for p in matched}
        for name in dp_names:
            if name.lower() not in found_names:
                logger.warning('Device Pool not found: %s', name)
                print(f"Device Pool not found: {name}")
        pools = matched
        logger.info('Matched %d Device Pools from CSV', len(pools))
    elif search_term:
        pools = [p for p in pools if search_term.lower() in p.get('name', '').lower()]
        logger.info('Found %d Device Pools matching "%s"', len(pools), search_term)

    if not pools:
        print("No matching Device Pools found")
        return []

    print(f"\n{'='*80}")
    print(f"Device Pools ({len(pools)} found)")
    print(f"{'='*80}\n")

    for pool in pools:
        pool_name = pool.get('name', 'Unknown')
        pool_uuid = pool.get('pkid', 'Unknown')

        logger.debug('Processing Device Pool: %s (%s)', pool_name, pool_uuid)

        deps_result = axl.find_device_pool_dependencies(pool_name)
        dependencies = deps_result.get('response', []) if deps_result.get('success') else []

        print(f"Device Pool: {pool_name} ({len(dependencies)} dependencies)")
        for dep in dependencies:
            dep_name = dep.get('name', 'Unknown')
            dep_type = dep.get('type', 'Unknown')
            if list_deps:
                print(f"  - {dep_name} ({dep_type})")
            logger.debug('  Dependency: %s (%s)', dep_name, dep_type)

        if not dependencies:
            no_dependency_pools.append({
                'name': pool_name,
                'uuid': pool_uuid
            })

    return no_dependency_pools


def run_operation_on_cluster(cluster_data, cluster_credentials, script_dir, logger, dp_names, search_term, list_deps):
    """Run the Device Pool listing on a single cluster"""
    cluster_name = cluster_data.get('name', 'unknown')
    try:
        cluster_name = cluster_data['name']
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

        no_dep_pools = display_device_pools(axl, logger, dp_names=dp_names, search_term=search_term, list_deps=list_deps)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_pools, cluster_name, axl)
    except Exception as e:
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return (False, [], cluster_name, None)


def run_on_all_clusters(script_dir, clusters_data, logger, dp_names, search_term, list_deps):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    all_no_dep_pools = []
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(cluster, cluster_credentials, script_dir, logger, dp_names, search_term, list_deps)
        success, no_dep_pools, cluster_name, axl = result
        if success:
            successful += 1
            for pool in no_dep_pools:
                pool['cluster'] = cluster_name
            all_no_dep_pools.extend(no_dep_pools)
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_pools, cluster_axl_map


def delete_device_pools(pools, cluster_axl_map, logger):
    """Delete Device Pools organized by cluster"""
    if not pools:
        print("No Device Pools to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"Device Pools with No Dependencies ({len(pools)} found)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for pool in pools:
        print(f"  - {pool.get('name')} (Cluster: {pool.get('cluster')})")
        clusters_set.add(pool.get('cluster'))

    print(f"\nTotal: {len(pools)} Device Pools across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    if not prompt_yes_no('Delete these Device Pools?', default=False):
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0

    clusters_data = {}
    for pool in pools:
        cluster_name = pool.get('cluster')
        clusters_data.setdefault(cluster_name, []).append(pool)

    successful_deletes = 0
    failed_deletes = 0

    print("\nDeleting Device Pools...\n")
    for cluster_name, cluster_pools in clusters_data.items():
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += len(cluster_pools)
            continue

        axl = cluster_axl_map[cluster_name]
        print(f"{'-'*80}")
        print(f"Cluster: {cluster_name}")
        print(f"{'-'*80}\n")

        for pool in cluster_pools:
            pool_name = pool.get('name')
            try:
                result = axl.remove_Device_Pool(pool_name)
                if result.get('success'):
                    print(f"  ✓ Deleted: {pool_name}")
                    logger.info('Deleted Device Pool: %s', pool_name)
                    successful_deletes += 1
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {pool_name} - {error_msg}")
                    logger.error('Failed to delete Device Pool %s: %s', pool_name, error_msg)
                    failed_deletes += 1
            except Exception as e:
                print(f"  ✗ Exception: {pool_name} - {str(e)}")
                logger.error('Exception deleting Device Pool %s: %s', pool_name, str(e))
                failed_deletes += 1

        print()

    return successful_deletes, failed_deletes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remediate Device Pools - List Dependencies and Delete Without Dependencies')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    parser.add_argument('--listD', action='store_true', help='List each dependency (name and type) under its Device Pool')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remediate-device-pools.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Device Pools - Started")

    print("="*80)
    print("Remediate Device Pools")
    print("="*80)

    dp_names = None
    search_term = None
    if prompt_yes_no('\nUse CSV?', default=False):
        csv_file = input('Enter CSV file name or full path [_DATA/devicePools.csv]: ').strip() or str(basepath.parent / '_DATA' / 'devicePools.csv')
        logger.info("Using CSV file for Device Pool names: %s", csv_file)
        dp_names = read_device_pool_names_from_csv(csv_file, logger)
        if not dp_names:
            print("No Device Pool names loaded from CSV")
            sys.exit(1)
    else:
        search_term = input("Enter text to search/filter Device Pool names (or press Enter to list all): ").strip()

    all_no_dep_pools = []
    cluster_axl_map = {}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            all_no_dep_pools, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger, dp_names, search_term, args.listD)
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

            no_dep_pools = display_device_pools(axl, logger, dp_names=dp_names, search_term=search_term, list_deps=args.listD)
            for pool in no_dep_pools:
                pool['cluster'] = cluster['name']
            all_no_dep_pools = no_dep_pools
            cluster_axl_map[cluster['name']] = axl

    else:
        # No clusters found in CSV - single cluster mode with manual input
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

        no_dep_pools = display_device_pools(axl, logger, dp_names=dp_names, search_term=search_term, list_deps=args.listD)
        for pool in no_dep_pools:
            pool['cluster'] = cluster['name']
        all_no_dep_pools = no_dep_pools
        cluster_axl_map[cluster['name']] = axl

    # Offer to delete Device Pools with no dependencies
    if all_no_dep_pools:
        successful, failed = delete_device_pools(all_no_dep_pools, cluster_axl_map, logger)

        print(f"\n{'='*80}")
        print(f"Deletion Summary")
        print(f"{'='*80}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total: {successful + failed}")
        print(f"{'='*80}\n")

        logger.info("Deletion Summary - Successful: %d, Failed: %d, Total: %d", successful, failed, successful + failed)
    else:
        print("\nNo Device Pools without dependencies to delete")

    logger.info("Remediate Device Pools - Completed")
