#!/usr/bin/env python3

"""
Compare Advertised Patterns with Route Patterns in CUCM

Connects to CUCM, retrieves all advertised patterns and route patterns,
compares the last 10 digits of each, and exports patterns that exist in
one set but not the other to a CSV file.

CUCM Cluster: select from clusters.csv or provide manually
Credentials: checks stored credentials in credentials.env

CSV Output Format:
pattern, patternType, source, lastTenDigits
- source: 'Advertised Only' or 'Route Only'
- lastTenDigits: Last 10 digits of the pattern (or full pattern if < 10 digits)

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



def extract_last_ten_digits(pattern):
    """
    Extract the last 10 digits from a pattern string.
    Handles patterns with special characters like X, ., #, etc.

    Args:
        pattern (str): The pattern string

    Returns:
        str: Last 10 characters of the pattern (or full pattern if < 10 chars)
    """
    return pattern[-10:] if pattern else ''


def compare_patterns(advertised_patterns, route_patterns):
    """
    Compare advertised patterns and route patterns, returning mismatches.

    Args:
        advertised_patterns (list): List of advertised pattern dicts
        route_patterns (list): List of route pattern dicts

    Returns:
        list: List of dicts with pattern info and source of mismatch
    """
    # Extract last 10 digits from each pattern set
    adv_last_ten = {}
    for pattern_obj in advertised_patterns:
        pattern = pattern_obj.get('pattern', '')
        last_ten = extract_last_ten_digits(pattern)
        adv_last_ten[last_ten] = {
            'pattern': pattern,
            'patternType': pattern_obj.get('patternType', ''),
        }

    route_last_ten = set()
    for pattern_obj in route_patterns:
        pattern = pattern_obj.get('pattern', '')
        last_ten = extract_last_ten_digits(pattern)
        route_last_ten.add(last_ten)

    # Find patterns that exist in one set but not the other
    mismatches = []

    # Advertised patterns not in route patterns
    for last_ten, adv_info in adv_last_ten.items():
        if last_ten not in route_last_ten:
            mismatches.append({
                'pattern': adv_info['pattern'],
                'patternType': adv_info['patternType'],
                'source': 'Advertised Only',
                'lastTenDigits': last_ten,
            })

    # Route patterns not in advertised patterns (need to re-fetch for route info)
    route_pattern_objs = {extract_last_ten_digits(p.get('pattern', '')): p
                          for p in route_patterns}

    for last_ten in route_last_ten:
        if last_ten not in adv_last_ten:
            route_info = route_pattern_objs.get(last_ten, {})
            mismatches.append({
                'pattern': route_info.get('pattern', ''),
                'patternType': 'Route Only',
                'source': 'Route Only',
                'lastTenDigits': last_ten,
            })

    return sorted(mismatches, key=lambda x: (x['source'] != 'Advertised Only', x['lastTenDigits']))


def run_comparison(axl, logger, cluster_name, server):
    """Run pattern comparison on a single cluster."""
    logger.info('Fetching advertised patterns from CUCM')
    adv_result = axl.list_advertised_patterns()

    if not adv_result.get('success'):
        logger.error(f'Failed to retrieve advertised patterns: {adv_result.get("error")}')
        print(f'Error: {adv_result.get("error")}')
        return False

    adv_response = adv_result.get('response', [])
    if not adv_response or adv_response == '':
        advertised_patterns = []
    elif isinstance(adv_response, list):
        advertised_patterns = adv_response
    else:
        advertised_patterns = [adv_response]

    logger.info(f'Retrieved {len(advertised_patterns)} advertised patterns')

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

    logger.info('Comparing advertised patterns with route patterns')
    mismatches = compare_patterns(advertised_patterns, route_patterns)

    if mismatches or len(advertised_patterns) > 0 or len(route_patterns) > 0:
        export_comparison_to_csv(mismatches, len(advertised_patterns), len(route_patterns), server)
    else:
        logger.warning('No patterns to compare')
        print('No patterns to compare')

    return True


def export_comparison_to_csv(mismatches, adv_count, route_count, server=''):
    """
    Export comparison results to a CSV file with timestamp

    Args:
        mismatches (list): List of mismatch dictionaries
        adv_count (int): Total advertised patterns count
        route_count (int): Total route patterns count
        server (str): Server name to include in filename
    """
    timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
    if server:
        output_filename = f'pattern_comparison-{server}-{timestamp}.csv'
    else:
        output_filename = f'pattern_comparison-{timestamp}.csv'

    adv_only_count = len([m for m in mismatches if m["source"] == "Advertised Only"])
    route_only_count = len([m for m in mismatches if m["source"] == "Route Only"])

    try:
        with open(output_filename, 'w', newline='', encoding='utf8') as csvfile:
            # Write summary as comments first
            csvfile.write(f'# Total Advertised Patterns: {adv_count}\n')
            csvfile.write(f'# Total Route Patterns: {route_count}\n')
            csvfile.write(f'# Mismatched Patterns: {len(mismatches)}\n')
            csvfile.write(f'# Advertised Only: {adv_only_count}\n')
            csvfile.write(f'# Route Only: {route_only_count}\n\n')

            fieldnames = ['pattern', 'patternType', 'source', 'lastTenDigits']
            writer = DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for mismatch in mismatches:
                writer.writerow(mismatch)

            logger.info(f'Successfully exported {len(mismatches)} mismatched patterns to {output_filename}')
            print(f'\nPattern comparison exported to: {output_filename}')
            print(f'Total Advertised Patterns: {adv_count}')
            print(f'Total Route Patterns: {route_count}')
            print(f'Mismatched Patterns: {len(mismatches)}')
            print(f'  - Advertised Only: {adv_only_count}')
            print(f'  - Route Only: {route_only_count}')

    except IOError as e:
        logger.error(f'Error writing to CSV file: {e}')
        print(f'Error writing CSV file: {e}')


def run_operation_on_cluster(basepath, cluster_data, cluster_credentials, logger):
    """Run pattern comparison on a single cluster."""
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

        success = run_comparison(axl, logger, cluster_name, server)

        logger.info('Completed cluster: %s', cluster_name)
        if success:
            print(f"✓ Completed {cluster_name} ({server})")
        return success
    except Exception as e:
        logger.error('Error processing cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, logger):
    """Run comparison on all clusters sequentially."""
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

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-compare-advp-rp.log"
    logger = setup_logger(log_file)
    logger.info("Compare Advertised Patterns with Route Patterns - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            run_on_all_clusters(basepath, clusters_data, logger)
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

            run_comparison(axl, logger, cluster['name'], server)

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

        run_comparison(axl, logger, cluster['name'], server)
