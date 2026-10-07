#!/usr/bin/env python3
# TITLE: Common Device Config Remediate

"""
Remediate Common Device Configuration - List and Delete Without Dependencies
Lists Common Device Configurations and their dependencies (devices, device pools, device profiles),
then optionally deletes configurations with no dependencies

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


def display_common_device_configs(axl, logger, search_term):
    """List Common Device Configurations matching the search term and their dependencies"""
    no_dependency_configs = []

    logger.info('Fetching Common Device Configurations...')
    configs_result = axl.list_common_device_configs()

    if not configs_result.get('success'):
        logger.error('Failed to fetch Common Device Configurations: %s', configs_result.get('error'))
        print(f"Error: {configs_result.get('error')}")
        return []

    configs = configs_result.get('response')

    if not configs:
        logger.info('No Common Device Configurations found')
        print("No Common Device Configurations found")
        return []

    if search_term:
        configs = [c for c in configs if search_term.lower() in c.get('name', '').lower()]
        logger.info('Found %d Common Device Configurations matching "%s"', len(configs), search_term)
        if not configs:
            print(f"No Common Device Configurations found matching '{search_term}'")
            return []
    else:
        logger.info('Found %d Common Device Configurations', len(configs))

    print(f"\n{'='*80}")
    print(f"Common Device Configurations ({len(configs)} found)")
    print(f"{'='*80}\n")

    for config in configs:
        config_name = config.get('name', 'Unknown')
        config_uuid = config.get('pkid', 'Unknown')

        logger.info('Processing Common Device Configuration: %s (%s)', config_name, config_uuid)

        deps_result = axl.find_common_device_config_dependencies(config_name)
        dependencies = deps_result.get('response', []) if deps_result.get('success') else []

        print(f"Common Device Configuration: {config_name}")
        if dependencies:
            print(f"  Dependencies ({len(dependencies)}):")
            for dep in dependencies:
                dep_name = dep.get('name', 'Unknown')
                dep_type = dep.get('type', 'Unknown')
                print(f"    - {dep_name} ({dep_type})")
                logger.debug('  Dependency: %s (%s)', dep_name, dep_type)
        else:
            print(f"  No dependencies found")
            no_dependency_configs.append({
                'name': config_name,
                'uuid': config_uuid
            })
        print()

    return no_dependency_configs


def run_operation_on_cluster(cluster_data, cluster_credentials, script_dir, logger, search_term):
    """Run the Common Device Configuration listing on a single cluster"""
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

        no_dep_configs = display_common_device_configs(axl, logger, search_term)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_configs, cluster_name, axl)
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
    all_no_dep_configs = []
    cluster_axl_map = {}

    for cluster in clusters_data:
        result = run_operation_on_cluster(cluster, cluster_credentials, script_dir, logger, search_term)
        success, no_dep_configs, cluster_name, axl = result
        if success:
            successful += 1
            for config in no_dep_configs:
                config['cluster'] = cluster_name
            all_no_dep_configs.extend(no_dep_configs)
            cluster_axl_map[cluster_name] = axl
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_configs, cluster_axl_map


def delete_configs(configs, cluster_axl_map, logger):
    """Delete Common Device Configurations organized by cluster"""
    if not configs:
        print("No Common Device Configurations to delete")
        return 0, 0

    print(f"\n{'='*80}")
    print(f"Common Device Configurations to Delete ({len(configs)} found)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for config in configs:
        print(f"  - {config.get('name')} (Cluster: {config.get('cluster')})")
        clusters_set.add(config.get('cluster'))

    print(f"\nTotal: {len(configs)} configurations across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    mode = prompt_delete_mode('Delete these Common Device Configurations?')
    if mode == 'n':
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        return 0, 0
    individual = (mode == 'i')
    logger.info('Delete mode: %s', 'individual' if individual else 'all')

    # Organize by cluster
    clusters_data = {}
    for config in configs:
        cluster_name = config.get('cluster')
        if cluster_name not in clusters_data:
            clusters_data[cluster_name] = []
        clusters_data[cluster_name].append(config)

    successful_deletes = 0
    failed_deletes = 0

    print("\nDeleting Common Device Configurations...\n")
    for cluster_name, cluster_configs in clusters_data.items():
        if cluster_name not in cluster_axl_map:
            logger.warning('No AXL client for cluster %s', cluster_name)
            failed_deletes += len(cluster_configs)
            continue

        axl = cluster_axl_map[cluster_name]
        print(f"{'-'*80}")
        print(f"Cluster: {cluster_name}")
        print(f"{'-'*80}\n")

        for config in cluster_configs:
            config_name = config.get('name')
            if individual and not prompt_yes_no(f"Delete '{config_name}'?", default=False):
                print(f"  - Skipped: {config_name}")
                logger.info('Skipped: %s', config_name)
                continue
            try:
                result = axl.delete_common_device_config(config_name)
                if result.get('success'):
                    print(f"  ✓ Deleted: {config_name}")
                    logger.info('Deleted Common Device Configuration: %s', config_name)
                    successful_deletes += 1
                else:
                    error_msg = result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {config_name} - {error_msg}")
                    logger.error('Failed to delete Common Device Configuration %s: %s', config_name, error_msg)
                    failed_deletes += 1
            except Exception as e:
                print(f"  ✗ Exception: {config_name} - {str(e)}")
                logger.error('Exception deleting Common Device Configuration %s: %s', config_name, str(e))
                failed_deletes += 1

        print()

    return successful_deletes, failed_deletes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remediate Common Device Configuration - List and Delete Without Dependencies')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remediate-common-device-config.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Remediate Common Device Configuration - Started")

    search_term = input("Enter text to search/filter Common Device Configuration names (or press Enter to list all): ").strip()

    all_no_dep_configs = []
    cluster_axl_map = {}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            all_no_dep_configs, cluster_axl_map = run_on_all_clusters(script_dir, clusters_data, logger, search_term)
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

            no_dep_configs = display_common_device_configs(axl, logger, search_term)
            for config in no_dep_configs:
                config['cluster'] = cluster['name']
            all_no_dep_configs = no_dep_configs
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

        no_dep_configs = display_common_device_configs(axl, logger, search_term)
        for config in no_dep_configs:
            config['cluster'] = cluster['name']
        all_no_dep_configs = no_dep_configs
        cluster_axl_map[cluster['name']] = axl

    # Offer to delete Common Device Configurations with no dependencies
    if all_no_dep_configs:
        successful, failed = delete_configs(all_no_dep_configs, cluster_axl_map, logger)

        print(f"\n{'='*80}")
        print(f"Deletion Summary")
        print(f"{'='*80}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total: {successful + failed}")
        print(f"{'='*80}\n")

        logger.info("Deletion Summary - Successful: %d, Failed: %d, Total: %d", successful, failed, successful + failed)
    else:
        print("\nNo Common Device Configurations without dependencies to delete")

    logger.info("Remediate Common Device Configuration - Completed")
