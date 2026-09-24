#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Remediate Locations - List and Delete Without Dependencies
Lists locations and their dependencies, then optionally deletes locations with no dependencies
Excludes system locations like Phantom, Shadow, and Hub_None

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


SYSTEM_LOCATIONS = {'Phantom', 'Shadow', 'Hub_None'}
MAX_WORKERS = 10


def fetch_location_dependencies(axl, location_name):
    """Fetch dependencies for a single location (used in parallel execution)"""
    deps_result = axl.find_location_dependencies(location_name)
    return {
        'location_name': location_name,
        'deps_result': deps_result,
        'dependencies': deps_result.get('response', []) if deps_result.get('success') else []
    }


def display_locations(axl, logger, script_dir, debug_mode=False):
    """List all locations and their dependencies"""
    search_term = input("Enter location name to search (or press Enter to list all): ").strip()
    no_dependency_locations = []

    logger.info('Fetching locations...')
    locations_result = axl.list_Locations()

    if not locations_result.get('success'):
        logger.error('Failed to fetch locations: %s', locations_result.get('error'))
        print(f"Error: {locations_result.get('error')}")
        return []

    locations = locations_result.get('response')

    if not locations:
        logger.info('No locations found')
        print("No locations found")
        return []

    # Filter out system locations and apply search in one pass
    filtered_locations = []
    for location in locations:
        location_name = location.get('name', 'Unknown')
        if location_name not in SYSTEM_LOCATIONS:
            if not search_term or search_term.lower() in location_name.lower():
                filtered_locations.append(location)

    if not filtered_locations:
        if search_term:
            logger.info('No locations found matching "%s"', search_term)
            print(f"No locations found matching '{search_term}'")
        else:
            logger.info('No custom locations found (only system locations)')
            print("No custom locations found (system locations excluded)")
        return []

    locations = filtered_locations
    if search_term:
        logger.info('Found %d locations matching "%s"', len(locations), search_term)
    else:
        logger.info('Found %d custom locations', len(locations))

    print(f"\n{'='*80}")
    print(f"Locations ({len(locations)} locations)")
    print(f"{'='*80}\n")

    logger.info('Fetching dependencies for %d locations in parallel', len(locations))

    # Fetch all dependencies in parallel
    location_deps = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_location_dependencies, axl, location.get('name', 'Unknown')): location
            for location in locations
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                location_deps[result['location_name']] = result
            except Exception as e:
                location = futures[future]
                location_name = location.get('name', 'Unknown')
                logger.error('Failed to fetch dependencies for %s: %s', location_name, str(e))

    # Display results in original order
    for location in locations:
        location_name = location.get('name', 'Unknown')
        logger.info('Processing location: %s', location_name)

        if location_name not in location_deps:
            logger.warning('No dependency result for location: %s', location_name)
            print(f"Location: {location_name}")
            print(f"  Error: Failed to fetch dependencies")
            print()
            continue

        result = location_deps[location_name]
        deps_result = result['deps_result']
        dependencies = result['dependencies']

        if debug_mode:
            logger.info('Location: %s - Dependencies result: %s', location_name, deps_result)

        print(f"Location: {location_name}")
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
            no_dependency_locations.append({
                'name': location_name
            })
        print()

    return no_dependency_locations


def run_operation_on_cluster(script_dir, cluster_data, cluster_credentials, logger, debug_mode=False):
    """Run the location listing on a single cluster"""
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

        no_dep_locations = display_locations(axl, logger, script_dir, debug_mode=debug_mode)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_locations, cluster_name, axl)
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
    all_no_dep_locations = []
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(script_dir, cluster, cluster_credentials, logger, debug_mode=debug_mode)
        success, no_dep_locations, cluster_name, axl = result
        if success:
            successful += 1
            for location in no_dep_locations:
                location['cluster'] = cluster_name
            all_no_dep_locations.extend(no_dep_locations)
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_locations, cluster_axl_map


def delete_locations(locations, cluster_axl_map, logger):
    """Delete locations organized by cluster"""
    if not locations:
        print("No locations to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"Locations to Delete ({len(locations)} locations)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for location in locations:
        print(f"  - {location.get('name')} (Cluster: {location.get('cluster')})")
        clusters_set.add(location.get('cluster'))

    print(f"\nTotal: {len(locations)} locations across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    if not prompt_yes_no('Delete these locations?', default=False):
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0

    # Organize by cluster
    clusters_data = {}
    for location in locations:
        cluster_name = location.get('cluster')
        if cluster_name not in clusters_data:
            clusters_data[cluster_name] = []
        clusters_data[cluster_name].append(location)

    successful_deletes = 0
    failed_deletes = 0

    # Delete locations by cluster
    print("\nDeleting locations...\n")
    for cluster_name, cluster_locations in clusters_data.items():
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += len(cluster_locations)
            continue

        axl = cluster_axl_map[cluster_name]
        print(f"{'-'*80}")
        print(f"Cluster: {cluster_name}")
        print(f"{'-'*80}\n")

        for location in cluster_locations:
            location_name = location.get('name')
            try:
                result = axl.delete_location(location_name)
                if result.get('success'):
                    print(f"  ✓ Deleted: {location_name}")
                    logger.info('Deleted location: %s', location_name)
                    successful_deletes += 1
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {location_name} - {error_msg}")
                    logger.error('Failed to delete location %s: %s', location_name, error_msg)
                    failed_deletes += 1
            except Exception as e:
                print(f"  ✗ Exception: {location_name} - {str(e)}")
                logger.error('Exception deleting location %s: %s', location_name, str(e))
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
    parser = argparse.ArgumentParser(description='Remediate Locations - List and Delete Without Dependencies')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    parser.add_argument('--verbose', action='store_true', help='Show detailed dependency lookup information')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"_logs/{timestamp}-remediate-locations.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Locations - Started")

    use_multiple = False
    all_no_dep_locations = []
    cluster_axl_map = {}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            all_no_dep_locations, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger, debug_mode=args.verbose)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            axl = initialize_axl(cluster, script_dir)
            no_dep_locations = display_locations(axl, logger, script_dir, debug_mode=args.verbose)
            for location in no_dep_locations:
                location['cluster'] = cluster['name']
            all_no_dep_locations = no_dep_locations
            cluster_axl_map[cluster['name']] = axl

    else:
        # No clusters found in CSV - single cluster mode with manual input
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        axl = initialize_axl(cluster, script_dir)
        no_dep_locations = display_locations(axl, logger, script_dir, debug_mode=args.verbose)
        for location in no_dep_locations:
            location['cluster'] = cluster['name']
        all_no_dep_locations = no_dep_locations
        cluster_axl_map[cluster['name']] = axl

    # Offer to delete locations with no dependencies
    if all_no_dep_locations:
        successful, failed = delete_locations(all_no_dep_locations, cluster_axl_map, logger)

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
        print("\nNo locations without dependencies to delete")

    logger.info("Remediate Locations - Completed")
