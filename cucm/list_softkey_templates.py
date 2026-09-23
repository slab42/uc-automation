#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
List Softkey Templates and their dependencies
Lists custom softkey templates (excludes system templates like "Public Conference User")
and displays what devices/profiles use each template

Supports single or multiple CUCM clusters
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


def display_softkey_templates(axl, logger, script_dir):
    """List all softkey templates and their dependencies"""
    search_term = input("Enter template name to search (or press Enter to list all): ").strip()
    no_dependency_templates = []

    logger.info('Fetching softkey templates...')
    templates_result = axl.list_softkey_templates()

    if not templates_result.get('success'):
        logger.error('Failed to fetch softkey templates: %s', templates_result.get('error'))
        print(f"Error: {templates_result.get('error')}")
        return []

    templates = templates_result.get('response')

    if not templates:
        logger.info('No softkey templates found')
        print("No softkey templates found")
        return []

    # Load system templates that cannot be deleted
    system_templates = set()
    system_templates_file = script_dir.parent / '_DATA' / 'system_softkey_templates.txt'
    if system_templates_file.exists():
        try:
            with open(system_templates_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        system_templates.add(line)
            logger.info('Loaded %d system templates to exclude', len(system_templates))
        except Exception as e:
            logger.warning('Failed to load system templates file: %s', str(e))

    # Filter out system templates
    custom_templates = []
    for template in templates:
        template_name = template.get('name', 'Unknown')
        if template_name not in system_templates:
            custom_templates.append(template)

    if not custom_templates:
        logger.info('No custom softkey templates found (only system templates)')
        print("No custom softkey templates found (system templates excluded)")
        return []

    # Apply search filter if provided
    if search_term:
        filtered_templates = []
        for template in custom_templates:
            template_name = template.get('name', 'Unknown')
            if search_term.lower() in template_name.lower():
                filtered_templates.append(template)
        templates = filtered_templates
        logger.info('Found %d templates matching "%s"', len(templates), search_term)
        if not templates:
            print(f"No templates found matching '{search_term}'")
            return []
    else:
        templates = custom_templates
        logger.info('Found %d custom softkey templates', len(templates))

    print(f"\n{'='*80}")
    print(f"Softkey Templates ({len(templates)} templates)")
    print(f"{'='*80}\n")

    for template in templates:
        template_name = template.get('name', 'Unknown')
        template_uuid = template.get('pkid', 'Unknown')

        logger.info('Processing template: %s (%s)', template_name, template_uuid)

        deps_result = axl.find_softkey_template_dependencies(template_name)
        dependencies = deps_result.get('response', []) if deps_result.get('success') else []

        print(f"Template: {template_name}")
        if dependencies:
            print(f"  Dependencies ({len(dependencies)}):")
            for dep in dependencies:
                dep_name = dep.get('name', 'Unknown')
                dep_type = dep.get('type', 'Unknown')
                print(f"    - {dep_name} ({dep_type})")
                logger.debug('  Dependency: %s (%s)', dep_name, dep_type)
        else:
            print(f"  No dependencies found")
            no_dependency_templates.append({
                'name': template_name,
                'uuid': template_uuid
            })
        print()

    return no_dependency_templates


def run_operation_on_cluster(script_dir, cluster_data, cluster_credentials, logger):
    """Run the softkey template listing on a single cluster"""
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

        no_dep_templates = display_softkey_templates(axl, logger, script_dir)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return (True, no_dep_templates, cluster_name)
    except Exception as e:
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return (False, [], cluster_name)


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
    all_no_dep_templates = []

    for cluster in clusters_data:
        result = run_operation_on_cluster(script_dir, cluster, cluster_credentials, logger)
        success, no_dep_templates, cluster_name = result
        if success:
            successful += 1
            for template in no_dep_templates:
                template['cluster'] = cluster_name
            all_no_dep_templates.extend(no_dep_templates)
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")

    return all_no_dep_templates


def export_to_csv(templates, script_dir, logger):
    """Export templates with no dependencies to CSV file"""
    import csv
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    csv_file = script_dir.parent / '_DATA' / f'{timestamp}-softkey-templates-no-dependencies.csv'

    try:
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['cluster', 'name', 'uuid'])
            writer.writeheader()
            writer.writerows(templates)
        print(f"\n✓ Exported {len(templates)} templates to {csv_file}")
        logger.info('Exported %d templates to %s', len(templates), csv_file)
    except Exception as e:
        print(f"\n✗ Failed to export CSV: {str(e)}")
        logger.error('Failed to export CSV: %s', str(e))


if __name__ == '__main__':
    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"_logs/{timestamp}-list-softkey-templates.log"
    logger = setup_logger(log_file)
    logger.info("List Softkey Templates - Started")

    use_multiple = False
    all_no_dep_templates = []

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            if not clusters_data:
                print("No clusters found in clusters.csv")
                exit(1)

            all_no_dep_templates = run_on_all_clusters(script_dir, clusters_data, logger)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
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

            no_dep_templates = display_softkey_templates(axl, logger, script_dir)
            for template in no_dep_templates:
                template['cluster'] = cluster['name']
            all_no_dep_templates = no_dep_templates

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

        no_dep_templates = display_softkey_templates(axl, logger, script_dir)
        for template in no_dep_templates:
            template['cluster'] = cluster['name']
        all_no_dep_templates = no_dep_templates

    # Offer to export templates with no dependencies to CSV
    if all_no_dep_templates:
        export = prompt_yes_no(f'\nExport {len(all_no_dep_templates)} templates with no dependencies to CSV?', default=False)
        if export:
            export_to_csv(all_no_dep_templates, script_dir, logger)

    logger.info("List Softkey Templates - Completed")
