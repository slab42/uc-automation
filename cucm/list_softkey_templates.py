#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
List Softkey Templates and their dependencies
Pulls all softkey templates that are not system templates
and displays what devices/profiles use each template

Supports single or multiple CUCM clusters
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import time
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


def display_softkey_templates(axl, logger):
    """List all softkey templates and their dependencies"""
    logger.info('Fetching softkey templates...')
    templates_result = axl.list_softkey_templates()

    if not templates_result.get('success'):
        logger.error('Failed to fetch softkey templates: %s', templates_result.get('error'))
        print(f"Error: {templates_result.get('error')}")
        return

    templates = templates_result.get('response')

    # Display debug information
    debug_info = templates_result.get('debug_info', {})
    if debug_info:
        print(f"\n{'='*80}")
        print("DEBUG INFORMATION")
        print(f"{'='*80}")
        if debug_info.get('schema_query_attempted'):
            print(f"Schema query attempted: YES")
            if debug_info.get('schema_columns_found'):
                print(f"Softkey columns found: {', '.join(debug_info['schema_columns_found'])}")
            else:
                print(f"Softkey columns found: NONE")
        if debug_info.get('schema_query_error'):
            print(f"Schema query error: {debug_info['schema_query_error']}")
        if debug_info.get('fallback_queries_attempted'):
            print(f"Fallback queries attempted:")
            for query in debug_info['fallback_queries_attempted']:
                print(f"  - {query}")
        print(f"{'='*80}\n")

    if not templates:
        logger.info('No softkey templates found')
        print("No softkey templates found")
        return

    # Convert single result to list
    if not isinstance(templates, list):
        templates = [templates]

    logger.info('Found %d softkey templates', len(templates))
    print(f"\n{'='*80}")
    print(f"Softkey Templates ({len(templates)} templates in use)")
    print(f"{'='*80}\n")

    for template in templates:
        # Extract template name from response (can be dict or object)
        if isinstance(template, dict):
            template_name = template.get('name', 'Unknown')
        else:
            # Handle zeep response object
            template_name = str(getattr(template, 'name', str(template)))

        logger.info('Processing template: %s', template_name)

        # Get dependencies
        deps_result = axl.find_softkey_template_dependencies(template_name)
        dependencies = []
        if deps_result.get('success'):
            deps = deps_result.get('response')
            if deps:
                if not isinstance(deps, list):
                    deps = [deps]
                dependencies = deps

        print(f"Template: {template_name}")
        if dependencies:
            print(f"  Dependencies ({len(dependencies)}):")
            for dep in dependencies:
                if isinstance(dep, dict):
                    dep_name = dep.get('name', 'Unknown')
                    dep_type = dep.get('type', 'Unknown')
                else:
                    dep_name = getattr(dep, 'name', 'Unknown')
                    dep_type = getattr(dep, 'type', 'Unknown')
                print(f"    - {dep_name} ({dep_type})")
                logger.debug('  Dependency: %s (%s)', dep_name, dep_type)
        else:
            print(f"  No dependencies found")
        print()


def run_operation_on_cluster(basepath, cluster_data, cluster_credentials, logger):
    """Run the softkey template listing on a single cluster"""
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

        # Setup AXL Connection to CUCM
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = basepath / 'cucm' / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        display_softkey_templates(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, logger):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, cluster_credentials, logger):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-list-softkey-templates.log"
    logger = setup_logger(log_file)
    logger.info("List Softkey Templates - Started")

    use_multiple = False

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            if not clusters_data:
                print("No clusters found in clusters.csv")
                exit(1)

            run_on_all_clusters(basepath, clusters_data, logger)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUCM', cluster['name'])

            server = cluster['server']
            version = cluster['version']

            wsdl_dir = basepath / 'cucm' / 'schema' / version / 'AXLAPI.wsdl'
            wsdl = wsdl_dir.absolute().as_uri()
            axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

            display_softkey_templates(axl, logger)

    else:
        # No clusters found in CSV - single cluster mode with manual input
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUCM', cluster['name'])

        server = cluster['server']
        version = cluster['version']

        wsdl_dir = basepath / 'cucm' / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        display_softkey_templates(axl, logger)

    logger.info("List Softkey Templates - Completed")
