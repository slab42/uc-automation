#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Remediate Partitions - List and Delete Without Dependencies
Lists partitions and their dependencies, then optionally deletes partitions with no dependencies
Excludes system partitions

Supports single or multiple CUCM clusters

Arguments:
  --debug   Enable debug-level console logging (default: info level)
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import argparse
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


SYSTEM_PARTITIONS = set()
MAX_WORKERS = 20


def fetch_partition_dependencies(axl, partition_name):
    """Fetch dependencies for a single partition (used in parallel execution)"""
    deps_result = axl.find_partition_dependencies(partition_name)
    return {
        'partition_name': partition_name,
        'deps_result': deps_result,
        'dependencies': deps_result.get('response', []) if deps_result.get('success') else []
    }


def display_partitions(axl, logger, script_dir, debug_mode=False):
    """List all partitions and their dependencies"""
    search_term = input("Enter partition name to search (or press Enter to list all): ").strip()
    no_dependency_partitions = []

    logger.info('Fetching partitions...')
    partitions_result = axl.list_RoutePartitions()

    if not partitions_result.get('success'):
        logger.error('Failed to fetch partitions: %s', partitions_result.get('error'))
        print(f"Error: {partitions_result.get('error')}")
        return []

    partitions = partitions_result.get('response')

    if not partitions:
        logger.info('No partitions found')
        print("No partitions found")
        return []

    # Filter out system partitions and apply search in one pass
    filtered_partitions = []
    for partition in partitions:
        partition_name = partition.get('name', 'Unknown')
        if partition_name not in SYSTEM_PARTITIONS:
            if not search_term or search_term.lower() in partition_name.lower():
                filtered_partitions.append(partition)

    if not filtered_partitions:
        if search_term:
            logger.info('No partitions found matching "%s"', search_term)
            print(f"No partitions found matching '{search_term}'")
        else:
            logger.info('No custom partitions found (only system partitions)')
            print("No custom partitions found (system partitions excluded)")
        return []

    partitions = filtered_partitions
    if search_term:
        logger.info('Found %d partitions matching "%s"', len(partitions), search_term)
    else:
        logger.info('Found %d custom partitions', len(partitions))

    print(f"\n{'='*80}")
    print(f"Partitions ({len(partitions)} partitions)")
    print(f"{'='*80}\n")

    logger.info('Fetching dependencies for %d partitions in parallel', len(partitions))

    # Fetch all dependencies in parallel
    partition_deps = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_partition_dependencies, axl, partition.get('name', 'Unknown')): partition
            for partition in partitions
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                partition_deps[result['partition_name']] = result
            except Exception as e:
                partition = futures[future]
                partition_name = partition.get('name', 'Unknown')
                logger.error('Failed to fetch dependencies for %s: %s', partition_name, str(e))

    # Display results in original order
    for partition in partitions:
        partition_name = partition.get('name', 'Unknown')
        logger.info('Processing partition: %s', partition_name)

        if partition_name not in partition_deps:
            logger.warning('No dependency result for partition: %s', partition_name)
            print(f"Partition: {partition_name}")
            print(f"  Error: Failed to fetch dependencies")
            print()
            continue

        result = partition_deps[partition_name]
        deps_result = result['deps_result']
        dependencies = result['dependencies']

        if debug_mode:
            logger.info('Partition: %s - Dependencies result: %s', partition_name, deps_result)

        print(f"Partition: {partition_name}")
        if dependencies:
            print(f"  Dependencies ({len(dependencies)}):")
            for dep in dependencies:
                dep_name = dep.get('name', 'Unknown')
                dep_type = dep.get('type', 'Unknown')
                print(f"    - {dep_name} ({dep_type})")
                logger.debug('  Dependency: %s (%s)', dep_name, dep_type)
        else:
            print(f"  No dependencies found")
            if debug_mode:
                print(f"    [DEBUG] Full result: {deps_result}")
                if 'debug' in deps_result:
                    print(f"    [DEBUG] Query info:")
                    for debug_line in deps_result.get('debug', []):
                        print(f"      {debug_line}")
            no_dependency_partitions.append({
                'name': partition_name
            })
        print()

    return no_dependency_partitions


def run_operation_on_cluster(script_dir, cluster_data, cluster_credentials, logger, debug_mode=False):
    """Run the partition listing on a single cluster"""
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

        no_dep_partitions = display_partitions(axl, logger, script_dir, debug_mode=debug_mode)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_partitions, cluster_name, axl)
    except Exception as e:
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return (False, [], cluster_name, None)


def run_on_all_clusters(script_dir, clusters_data, logger, debug_mode=False):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    all_no_dep_partitions = []
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(script_dir, cluster, cluster_credentials, logger, debug_mode=debug_mode)
        success, no_dep_partitions, cluster_name, axl = result
        if success:
            successful += 1
            for partition in no_dep_partitions:
                partition['cluster'] = cluster_name
            all_no_dep_partitions.extend(no_dep_partitions)
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_partitions, cluster_axl_map


def delete_partitions(partitions, cluster_axl_map, logger):
    """Delete partitions organized by cluster"""
    if not partitions:
        print("No partitions to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"Partitions to Delete ({len(partitions)} partitions)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for partition in partitions:
        print(f"  - {partition.get('name')} (Cluster: {partition.get('cluster')})")
        clusters_set.add(partition.get('cluster'))

    print(f"\nTotal: {len(partitions)} partitions across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    if not prompt_yes_no('Delete these partitions?', default=False):
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0

    # Organize by cluster
    clusters_data = {}
    for partition in partitions:
        cluster_name = partition.get('cluster')
        if cluster_name not in clusters_data:
            clusters_data[cluster_name] = []
        clusters_data[cluster_name].append(partition)

    successful_deletes = 0
    failed_deletes = 0

    # Delete partitions by cluster
    print("\nDeleting partitions...\n")
    for cluster_name, cluster_partitions in clusters_data.items():
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += len(cluster_partitions)
            continue

        axl = cluster_axl_map[cluster_name]
        print(f"{'-'*80}")
        print(f"Cluster: {cluster_name}")
        print(f"{'-'*80}\n")

        for partition in cluster_partitions:
            partition_name = partition.get('name')
            try:
                result = axl.delete_partition(partition_name)
                if result.get('success'):
                    print(f"  ✓ Deleted: {partition_name}")
                    logger.info('Deleted partition: %s', partition_name)
                    successful_deletes += 1
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {partition_name} - {error_msg}")
                    logger.error('Failed to delete partition %s: %s', partition_name, error_msg)
                    failed_deletes += 1
            except Exception as e:
                print(f"  ✗ Exception: {partition_name} - {str(e)}")
                logger.error('Exception deleting partition %s: %s', partition_name, str(e))
                failed_deletes += 1

        print()

    return successful_deletes, failed_deletes


def initialize_axl(cluster, script_dir):
    """Initialize AXL client for a cluster"""
    username, password = load_credentials('CUCM', cluster['name'])
    server = cluster['server']
    version = cluster['version']

    wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdl_dir.absolute().as_uri()
    return AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remediate Partitions - List and Delete Without Dependencies')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    parser.add_argument('--verbose', action='store_true', help='Show detailed dependency lookup information')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"_logs/{timestamp}-remediate-partitions.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Partitions - Started")

    use_multiple = False
    all_no_dep_partitions = []
    cluster_axl_map = {}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            all_no_dep_partitions, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger, debug_mode=args.verbose)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            axl = initialize_axl(cluster, script_dir)
            no_dep_partitions = display_partitions(axl, logger, script_dir, debug_mode=args.verbose)
            for partition in no_dep_partitions:
                partition['cluster'] = cluster['name']
            all_no_dep_partitions = no_dep_partitions
            cluster_axl_map[cluster['name']] = axl

    else:
        # No clusters found in CSV - single cluster mode with manual input
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        axl = initialize_axl(cluster, script_dir)
        no_dep_partitions = display_partitions(axl, logger, script_dir, debug_mode=args.verbose)
        for partition in no_dep_partitions:
            partition['cluster'] = cluster['name']
        all_no_dep_partitions = no_dep_partitions
        cluster_axl_map[cluster['name']] = axl

    # Offer to delete partitions with no dependencies
    if all_no_dep_partitions:
        successful, failed = delete_partitions(all_no_dep_partitions, cluster_axl_map, logger)

        # Summary
        print(f"\n{'='*80}")
        print(f"Deletion Summary")
        print(f"{'='*80}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total: {successful + failed}")
        print(f"{'='*80}\n")

        logger.info("Deletion Summary - Successful: %d, Failed: %d, Total: %d", successful, failed, successful + failed)
    else:
        print("\nNo partitions without dependencies to delete")

    logger.info("Remediate Partitions - Completed")
