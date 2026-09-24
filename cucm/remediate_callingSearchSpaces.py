#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Remediate Calling Search Spaces - List and Delete Without Dependencies
Lists calling search spaces and their dependencies, then optionally deletes CSSs with no dependencies
Excludes system CSSs

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
from lookup_device_type import lookup_device_type, get_device_type_from_phone_data


SYSTEM_CSS = {'Default', 'Default_Intra_CompanyCS', 'Default_CUBE'}
MAX_WORKERS = 10


def fetch_css_dependencies(axl, css_name):
    """Fetch dependencies for a single CSS (used in parallel execution)"""
    deps_result = axl.find_css_dependencies(css_name)
    return {
        'css_name': css_name,
        'deps_result': deps_result,
        'dependencies': deps_result.get('response', []) if deps_result.get('success') else []
    }


def get_enriched_device_type(axl, dep_name, dep_type, cluster, script_dir, logger):
    """Get enriched device type information using device type lookup"""
    if not dep_name or dep_name == 'Unknown':
        return dep_type

    dep_type_lower = (dep_type or '').lower()
    if 'device pool' in dep_type_lower or 'dn' in dep_type_lower:
        return dep_type

    try:
        device_type = lookup_device_type(cluster, dep_name, script_dir, logger, axl_connection=axl)
        if device_type:
            return device_type
    except Exception as e:
        logger.debug('Failed to enrich device type for %s: %s', dep_name, str(e))

    return dep_type


def display_css_list(axl, logger, script_dir, cluster_data, debug_mode=False):
    """List all CSSs and their dependencies"""
    search_term = input("Enter CSS name to search (or press Enter to list all): ").strip()
    no_dependency_css = []

    logger.info('Fetching CSSs...')
    css_result = axl.list_Css()

    if not css_result.get('success'):
        logger.error('Failed to fetch CSSs: %s', css_result.get('error'))
        print(f"Error: {css_result.get('error')}")
        return []

    css_list = css_result.get('response')

    if not css_list:
        logger.info('No CSSs found')
        print("No CSSs found")
        return []

    # Filter out system CSSs and apply search in one pass
    filtered_css = []
    for css in css_list:
        css_name = css.get('name', 'Unknown')
        if css_name not in SYSTEM_CSS:
            if not search_term or search_term.lower() in css_name.lower():
                filtered_css.append(css)

    if not filtered_css:
        if search_term:
            logger.info('No CSSs found matching "%s"', search_term)
            print(f"No CSSs found matching '{search_term}'")
        else:
            logger.info('No custom CSSs found (only system CSSs)')
            print("No custom CSSs found (system CSSs excluded)")
        return []

    css_list = filtered_css
    if search_term:
        logger.info('Found %d CSSs matching "%s"', len(css_list), search_term)
    else:
        logger.info('Found %d custom CSSs', len(css_list))

    print(f"\n{'='*80}")
    print(f"Calling Search Spaces ({len(css_list)} CSSs)")
    print(f"{'='*80}\n")

    logger.info('Fetching dependencies for %d CSSs in parallel', len(css_list))

    # Fetch all dependencies in parallel
    css_deps = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_css_dependencies, axl, css.get('name', 'Unknown')): css
            for css in css_list
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                css_deps[result['css_name']] = result
            except Exception as e:
                css = futures[future]
                css_name = css.get('name', 'Unknown')
                logger.error('Failed to fetch dependencies for %s: %s', css_name, str(e))

    # Display results in original order
    for css in css_list:
        css_name = css.get('name', 'Unknown')
        logger.info('Processing CSS: %s', css_name)

        if css_name not in css_deps:
            logger.warning('No dependency result for CSS: %s', css_name)
            print(f"CSS: {css_name}")
            print(f"  Error: Failed to fetch dependencies")
            print()
            continue

        result = css_deps[css_name]
        deps_result = result['deps_result']
        dependencies = result['dependencies']

        if debug_mode:
            logger.info('CSS: %s - Dependencies result: %s', css_name, deps_result)

        print(f"CSS: {css_name}")
        if dependencies:
            print(f"  Dependencies ({len(dependencies)}):")
            for dep in dependencies:
                dep_name = dep.get('name', 'Unknown')
                dep_type = dep.get('type', 'Unknown')
                enriched_type = get_enriched_device_type(axl, dep_name, dep_type, cluster_data, script_dir, logger)
                print(f"    - {dep_name} ({enriched_type})")
                logger.debug('  Dependency: %s (%s)', dep_name, enriched_type)
        else:
            print(f"  No dependencies found")
            no_dependency_css.append({
                'name': css_name
            })
        print()

    return no_dependency_css


def run_operation_on_cluster(script_dir, cluster_data, cluster_credentials, logger, debug_mode=False):
    """Run the CSS listing on a single cluster"""
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

        no_dep_css = display_css_list(axl, logger, script_dir, cluster_data, debug_mode=debug_mode)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_css, cluster_name, axl)
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
    all_no_dep_css = []
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(script_dir, cluster, cluster_credentials, logger, debug_mode=debug_mode)
        success, no_dep_css, cluster_name, axl = result
        if success:
            successful += 1
            for css in no_dep_css:
                css['cluster'] = cluster_name
            all_no_dep_css.extend(no_dep_css)
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_css, cluster_axl_map


def delete_css_list(css_list, cluster_axl_map, logger):
    """Delete CSSs organized by cluster"""
    if not css_list:
        print("No CSSs to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"CSSs to Delete ({len(css_list)} CSSs)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for css in css_list:
        print(f"  - {css.get('name')} (Cluster: {css.get('cluster')})")
        clusters_set.add(css.get('cluster'))

    print(f"\nTotal: {len(css_list)} CSSs across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    if not prompt_yes_no('Delete these CSSs?', default=False):
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0

    # Organize by cluster
    clusters_data = {}
    for css in css_list:
        cluster_name = css.get('cluster')
        if cluster_name not in clusters_data:
            clusters_data[cluster_name] = []
        clusters_data[cluster_name].append(css)

    successful_deletes = 0
    failed_deletes = 0

    # Delete CSSs by cluster
    print("\nDeleting CSSs...\n")
    for cluster_name, cluster_css in clusters_data.items():
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += len(cluster_css)
            continue

        axl = cluster_axl_map[cluster_name]
        print(f"{'-'*80}")
        print(f"Cluster: {cluster_name}")
        print(f"{'-'*80}\n")

        for css in cluster_css:
            css_name = css.get('name')
            try:
                result = axl.remove_Calling_Search_Space(css_name)
                if result.get('success'):
                    print(f"  ✓ Deleted: {css_name}")
                    logger.info('Deleted CSS: %s', css_name)
                    successful_deletes += 1
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {css_name} - {error_msg}")
                    logger.error('Failed to delete CSS %s: %s', css_name, error_msg)
                    failed_deletes += 1
            except Exception as e:
                print(f"  ✗ Exception: {css_name} - {str(e)}")
                logger.error('Exception deleting CSS %s: %s', css_name, str(e))
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
    parser = argparse.ArgumentParser(description='Remediate Calling Search Spaces - List and Delete Without Dependencies')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    parser.add_argument('--verbose', action='store_true', help='Show detailed dependency lookup information')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"_logs/{timestamp}-remediate-callingSearchSpaces.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Calling Search Spaces - Started")

    use_multiple = False
    all_no_dep_css = []
    cluster_axl_map = {}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            all_no_dep_css, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger, debug_mode=args.verbose)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            axl = initialize_axl(cluster, script_dir)
            no_dep_css = display_css_list(axl, logger, script_dir, cluster, debug_mode=args.verbose)
            for css in no_dep_css:
                css['cluster'] = cluster['name']
            all_no_dep_css = no_dep_css
            cluster_axl_map[cluster['name']] = axl

    else:
        # No clusters found in CSV - single cluster mode with manual input
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        axl = initialize_axl(cluster, script_dir)
        no_dep_css = display_css_list(axl, logger, script_dir, cluster, debug_mode=args.verbose)
        for css in no_dep_css:
            css['cluster'] = cluster['name']
        all_no_dep_css = no_dep_css
        cluster_axl_map[cluster['name']] = axl

    # Offer to delete CSSs with no dependencies
    if all_no_dep_css:
        successful, failed = delete_css_list(all_no_dep_css, cluster_axl_map, logger)

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
        print("\nNo CSSs without dependencies to delete")

    logger.info("Remediate Calling Search Spaces - Completed")
