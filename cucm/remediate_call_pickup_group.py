#!/usr/bin/env python3
# TITLE: Call Pickup Group Remediate

"""
Remediate Call Pickup Group - List and Delete Without Dependencies
Lists Call Pickup Groups and their dependencies (directory numbers assigned as members
or via the line's Call Pickup Group setting), then optionally deletes groups with no
dependencies

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
from setup.prompt_utils import prompt_yes_no, prompt_delete_mode
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


def display_call_pickup_groups(axl, logger, search_term):
    """List Call Pickup Groups matching the search term and their dependencies"""
    no_dependency_groups = []

    logger.info('Fetching Call Pickup Groups...')
    groups_result = axl.list_call_pickup_groups()

    if not groups_result.get('success'):
        logger.error('Failed to fetch Call Pickup Groups: %s', groups_result.get('error'))
        print(f"Error: {groups_result.get('error')}")
        return []

    groups = groups_result.get('response')

    if not groups:
        logger.info('No Call Pickup Groups found')
        print("No Call Pickup Groups found")
        return []

    if search_term:
        groups = [g for g in groups if search_term.lower() in g.get('name', '').lower()]
        logger.info('Found %d Call Pickup Groups matching "%s"', len(groups), search_term)
        if not groups:
            print(f"No Call Pickup Groups found matching '{search_term}'")
            return []
    else:
        logger.info('Found %d Call Pickup Groups', len(groups))

    print(f"\n{'='*80}")
    print(f"Call Pickup Groups ({len(groups)} found)")
    print(f"{'='*80}\n")

    for group in groups:
        group_name = group.get('name', 'Unknown')
        group_uuid = group.get('pkid', 'Unknown')

        logger.info('Processing Call Pickup Group: %s (%s)', group_name, group_uuid)

        deps_result = axl.find_call_pickup_group_dependencies(group_name)
        if not deps_result.get('success'):
            logger.error('Failed to fetch dependencies for %s: %s', group_name, deps_result.get('error'))
        dependencies = deps_result.get('response', []) if deps_result.get('success') else []

        print(f"Call Pickup Group: {group_name}")
        if not deps_result.get('success'):
            print(f"  Error checking dependencies: {deps_result.get('error')}")
        elif dependencies:
            print(f"  Dependencies ({len(dependencies)}):")
            for dep in dependencies:
                dep_name = dep.get('name', 'Unknown')
                dep_type = dep.get('type', 'Unknown')
                print(f"    - {dep_name} ({dep_type})")
                logger.debug('  Dependency: %s (%s)', dep_name, dep_type)
        else:
            print(f"  No dependencies found")
            no_dependency_groups.append({
                'name': group_name,
                'uuid': group_uuid
            })
        print()

    return no_dependency_groups


def run_operation_on_cluster(cluster_data, cluster_credentials, script_dir, logger, search_term):
    """Run the Call Pickup Group listing on a single cluster"""
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

        no_dep_groups = display_call_pickup_groups(axl, logger, search_term)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_groups, cluster_name, axl)
    except Exception as e:
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return (False, [], cluster_name, None)


def run_on_all_clusters(script_dir, clusters_data, logger, search_term):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0
    all_no_dep_groups = []
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(cluster, cluster_credentials, script_dir, logger, search_term)
        success, no_dep_groups, cluster_name, axl = result
        if success:
            successful += 1
            for group in no_dep_groups:
                group['cluster'] = cluster_name
            all_no_dep_groups.extend(no_dep_groups)
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_groups, cluster_axl_map


def delete_groups(groups, cluster_axl_map, logger):
    """Delete Call Pickup Groups organized by cluster"""
    if not groups:
        print("No Call Pickup Groups to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"Call Pickup Groups to Delete ({len(groups)} found)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for group in groups:
        print(f"  - {group.get('name')} (Cluster: {group.get('cluster')})")
        clusters_set.add(group.get('cluster'))

    print(f"\nTotal: {len(groups)} groups across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    mode = prompt_delete_mode('Delete these Call Pickup Groups?')
    if mode == 'n':
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0
    individual = (mode == 'i')
    logger.info('Delete mode: %s', 'individual' if individual else 'all')

    # Organize by cluster
    clusters_data = {}
    for group in groups:
        cluster_name = group.get('cluster')
        if cluster_name not in clusters_data:
            clusters_data[cluster_name] = []
        clusters_data[cluster_name].append(group)

    successful_deletes = 0
    failed_deletes = 0

    print("\nDeleting Call Pickup Groups...\n")
    for cluster_name, cluster_groups in clusters_data.items():
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += len(cluster_groups)
            continue

        axl = cluster_axl_map[cluster_name]
        print(f"{'-'*80}")
        print(f"Cluster: {cluster_name}")
        print(f"{'-'*80}\n")

        for group in cluster_groups:
            group_name = group.get('name')
            if individual and not prompt_yes_no(f"Delete '{group_name}'?", default=False):
                print(f"  - Skipped: {group_name}")
                logger.info('Skipped: %s', group_name)
                continue
            try:
                result = axl.delete_call_pickup_group(group_name)
                if result.get('success'):
                    print(f"  ✓ Deleted: {group_name}")
                    logger.info('Deleted Call Pickup Group: %s', group_name)
                    successful_deletes += 1
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {group_name} - {error_msg}")
                    logger.error('Failed to delete Call Pickup Group %s: %s', group_name, error_msg)
                    failed_deletes += 1
            except Exception as e:
                print(f"  ✗ Exception: {group_name} - {str(e)}")
                logger.error('Exception deleting Call Pickup Group %s: %s', group_name, str(e))
                failed_deletes += 1

        print()

    return successful_deletes, failed_deletes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remediate Call Pickup Group - List and Delete Without Dependencies')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remediate-call-pickup-group.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Call Pickup Group - Started")

    search_term = input("Enter text to search/filter Call Pickup Group names (or press Enter to list all): ").strip()

    all_no_dep_groups = []
    cluster_axl_map = {}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            all_no_dep_groups, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger, search_term)
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

            no_dep_groups = display_call_pickup_groups(axl, logger, search_term)
            for group in no_dep_groups:
                group['cluster'] = cluster['name']
            all_no_dep_groups = no_dep_groups
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

        no_dep_groups = display_call_pickup_groups(axl, logger, search_term)
        for group in no_dep_groups:
            group['cluster'] = cluster['name']
        all_no_dep_groups = no_dep_groups
        cluster_axl_map[cluster['name']] = axl

    # Offer to delete Call Pickup Groups with no dependencies
    if all_no_dep_groups:
        successful, failed = delete_groups(all_no_dep_groups, cluster_axl_map, logger)

        print(f"\n{'='*80}")
        print(f"Deletion Summary")
        print(f"{'='*80}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total: {successful + failed}")
        print(f"{'='*80}\n")

        logger.info("Deletion Summary - Successful: %d, Failed: %d, Total: %d", successful, failed, successful + failed)
    else:
        print("\nNo Call Pickup Groups without dependencies to delete")

    logger.info("Remediate Call Pickup Group - Completed")
