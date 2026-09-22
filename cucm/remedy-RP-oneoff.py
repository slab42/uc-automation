#!/usr/bin/env python3

"""
Find Route Patterns with Dot Format but Missing Non-Dot Format

Connects to CUCM, retrieves all route patterns, and identifies patterns
that exist in dotted format (\+.12702106713) but NOT in standard format
(\+12702106713). Exports mismatches to a CSV file.

CUCM Cluster: select from clusters.csv or provide manually
Credentials: checks stored credentials in credentials.env

CSV Output Format:
dottedPattern, standardPattern, exists, description

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictWriter
from datetime import datetime
import time
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from ucmAPI import AXL



def filter_patterns_by_description(route_patterns, description_filter):
    """
    Filter route patterns by description text.

    Args:
        route_patterns (list): List of route pattern dicts
        description_filter (str): Text to match in description (case-insensitive)

    Returns:
        list: Filtered route patterns
    """
    if not description_filter or description_filter.strip() == '':
        return route_patterns

    filter_lower = description_filter.lower()
    return [p for p in route_patterns if filter_lower in (p.get('description', '') or '').lower()]


def find_dot_pattern_mismatches(route_patterns):
    """
    Find route patterns in dotted format without matching standard format.

    Args:
        route_patterns (list): List of route pattern dicts

    Returns:
        list: List of dicts with dotted pattern info and standard pattern status
    """
    # Build a set of all pattern strings for quick lookup
    all_patterns = {p.get('pattern', '') for p in route_patterns}

    mismatches = []

    for pattern_obj in route_patterns:
        pattern = pattern_obj.get('pattern', '')

        # Check if pattern starts with \+. (dotted format)
        if pattern.startswith('\\+.'):
            # Remove the dot to get the standard format
            standard_pattern = pattern.replace('\\+.', '\\+', 1)

            # Check if standard format exists in patterns
            if standard_pattern not in all_patterns:
                mismatches.append({
                    'dottedPattern': pattern,
                    'standardPattern': standard_pattern,
                    'exists': 'No',
                    'description': pattern_obj.get('description', ''),
                })
            else:
                mismatches.append({
                    'dottedPattern': pattern,
                    'standardPattern': standard_pattern,
                    'exists': 'Yes',
                    'description': pattern_obj.get('description', ''),
                })

    return sorted(mismatches, key=lambda x: (x['exists'] == 'Yes', x['dottedPattern']))


def export_mismatches_to_csv_impl(mismatches, total_route_count, filtered_route_count, description_filter, output_filename):

    missing_count = len([m for m in mismatches if m['exists'] == 'No'])
    has_count = len([m for m in mismatches if m['exists'] == 'Yes'])

    try:
        with open(output_filename, 'w', newline='', encoding='utf8') as csvfile:
            # Write summary as comments first
            csvfile.write(f'# Total Route Patterns: {total_route_count}\n')
            if description_filter:
                csvfile.write(f'# Description Filter: {description_filter}\n')
            csvfile.write(f'# Analyzed Patterns: {filtered_route_count}\n')
            csvfile.write(f'# Dotted Format Patterns Found: {len(mismatches)}\n')
            csvfile.write(f'# Missing Standard Format: {missing_count}\n')
            csvfile.write(f'# Has Standard Format: {has_count}\n\n')

            fieldnames = ['dottedPattern', 'standardPattern', 'exists', 'description']
            writer = DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for mismatch in mismatches:
                writer.writerow(mismatch)

            logger.info(f'Successfully exported {len(mismatches)} dotted format patterns to {output_filename}')
            print(f'\nDotted format pattern analysis exported to: {output_filename}')
            print(f'Total Route Patterns: {total_route_count}')
            if description_filter:
                print(f'Description Filter: {description_filter}')
            print(f'Analyzed Patterns: {filtered_route_count}')
            print(f'Dotted Format Patterns Found: {len(mismatches)}')
            print(f'Missing Standard Format: {missing_count}')
            print(f'Has Standard Format: {has_count}')

    except IOError as e:
        logger.error(f'Error writing to CSV file: {e}')
        print(f'Error writing CSV file: {e}')


def run_analysis(axl, logger, server, description_filter=''):
    """Run dotted pattern analysis on a single cluster."""
    logger.info('Fetching route patterns from CUCM')
    route_result = axl.list_route_patterns()

    if not route_result.get('success'):
        logger.error(f'Failed to retrieve route patterns: {route_result.get("error")}')
        print(f'Error: {route_result.get("error")}')
        return False

    route_response = route_result.get('response', [])
    if not route_response or route_response == '':
        route_patterns = []
    elif isinstance(route_response, list):
        route_patterns = route_response
    else:
        route_patterns = [route_response]

    logger.info(f'Retrieved {len(route_patterns)} route patterns')

    if description_filter:
        filtered_patterns = filter_patterns_by_description(route_patterns, description_filter)
        logger.info(f'Filtered to {len(filtered_patterns)} patterns matching description: {description_filter}')
        print(f'Filtered to {len(filtered_patterns)} patterns matching description')
    else:
        filtered_patterns = route_patterns
        logger.info('No description filter applied')

    logger.info('Analyzing route patterns for dotted format mismatches')
    mismatches = find_dot_pattern_mismatches(filtered_patterns)

    if len(route_patterns) > 0:
        timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
        if server:
            output_filename = f'remedy_RP_dotted-{server}-{timestamp}.csv'
        else:
            output_filename = f'remedy_RP_dotted-{timestamp}.csv'
        export_mismatches_to_csv_impl(mismatches, len(route_patterns), len(filtered_patterns), description_filter, output_filename)
    else:
        logger.warning('No route patterns to analyze')
        print('No route patterns to analyze')

    return True


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run analysis on a single cluster."""
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        description_filter = operation_params.get('description_filter', '')
        success = run_analysis(axl, logger, server, description_filter)

        logger.info('Completed cluster: %s', cluster_name)
        if success:
            print(f"✓ Completed {cluster_name} ({server})")
        return success
    except Exception as e:
        logger.error('Error processing cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run analysis on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, operation_params, cluster_credentials, logger):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remedy-rp-oneoff.log"
    logger = setup_logger(log_file)
    logger.info("Remedy Route Pattern Oneoff - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            description_filter = input('Filter patterns by description (leave blank for all): ').strip()
            operation_params = {'description_filter': description_filter}
            run_on_all_clusters(basepath, clusters_data, operation_params, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUCM', cluster['name'])

            server = cluster['server']
            version = cluster['version']

            wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
            wsdl = wsdl_dir.absolute().as_uri()
            axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

            description_filter = input('Filter patterns by description (leave blank for all): ').strip()
            run_analysis(axl, logger, server, description_filter)

    else:
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUCM', cluster['name'])

        server = cluster['server']
        version = cluster['version']

        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        description_filter = input('Filter patterns by description (leave blank for all): ').strip()
        run_analysis(axl, logger, server, description_filter)
