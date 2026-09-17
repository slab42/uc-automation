#!/usr/bin/env python3

"""
Remediate Duplicate-ish Route Patterns in CUCM

Identifies route patterns that start with '.+' and have a corresponding pattern
starting with '+' with the same 11-digit suffix, then prompts to delete the
'.+' pattern (keeping the '+' pattern as the canonical version).

CUCM Cluster: select from clusters.csv or provide manually
Credentials: checks stored credentials in credentials.env

For example:
  .+1234567890 (dot-plus prefix)
  +1234567890  (plus prefix)

If both exist with the same 11-digit suffix, prompts to delete the '.+' version.
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import time
import urllib3
from setup.logger import setup_logger
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from ucmAPI import AXL



def extract_last_eleven_digits(pattern):
    """Extract the last 11 characters from a pattern string."""
    return pattern[-11:] if pattern else ''


def find_duplicate_patterns(route_patterns):
    """
    Find route patterns where '.+<digits>' and '+<digits>' coexist with same 11-digit suffix.

    Args:
        route_patterns (list): List of route pattern dicts

    Returns:
        list: List of dicts with duplicatish pattern pairs (dot_plus_pattern, plus_pattern, last_11_digits)
    """
    dot_plus_patterns = {}
    plus_patterns = {}

    for pattern_obj in route_patterns:
        pattern = pattern_obj.get('pattern', '')

        if pattern.startswith(r'\+.'):
            last_11 = extract_last_eleven_digits(pattern)
            dot_plus_patterns[last_11] = {
                'pattern': pattern,
                'routePartitionName': pattern_obj.get('routePartitionName', ''),
                'description': pattern_obj.get('description', ''),
            }
        elif pattern.startswith(r'\+'):
            last_11 = extract_last_eleven_digits(pattern)
            plus_patterns[last_11] = {
                'pattern': pattern,
                'routePartitionName': pattern_obj.get('routePartitionName', ''),
                'description': pattern_obj.get('description', ''),
            }

    duplicates = []
    for last_11, dot_plus_info in dot_plus_patterns.items():
        if last_11 in plus_patterns:
            duplicates.append({
                'dot_plus_pattern': dot_plus_info['pattern'],
                'dot_plus_partition': dot_plus_info['routePartitionName'],
                'dot_plus_description': dot_plus_info['description'],
                'plus_pattern': plus_patterns[last_11]['pattern'],
                'plus_partition': plus_patterns[last_11]['routePartitionName'],
                'plus_description': plus_patterns[last_11]['description'],
                'last_11_digits': last_11,
            })

    return sorted(duplicates, key=lambda x: x['last_11_digits'])


def prompt_delete_patterns(duplicates, axl):
    """
    Prompt user for each duplicate pair and delete '.+' patterns as confirmed.

    Args:
        duplicates (list): List of duplicate dictionaries
        axl: AXL client instance
    """
    deleted_count = 0
    skipped_count = 0

    for dup in duplicates:
        dot_plus = dup['dot_plus_pattern']
        plus = dup['plus_pattern']
        dot_plus_desc = dup['dot_plus_description'] or '(no description)'
        plus_desc = dup['plus_description'] or '(no description)'

        print(f'\nDuplicate-ish patterns found:')
        print(f'  To DELETE (dot-plus):  {dot_plus}')
        print(f'    Description: {dot_plus_desc}')
        print(f'  To KEEP (plus):        {plus}')
        print(f'    Description: {plus_desc}')

        response = input(f'Delete {dot_plus}? (y/n): ').strip().lower()

        if response == 'y':
            result = axl.remove_Route_Pattern(
                pattern=dup['dot_plus_pattern'],
                routePartitionName=dup['dot_plus_partition']
            )
            if result.get('success'):
                logger.info(f'Deleted route pattern: {dot_plus}')
                print(f'Deleted: {dot_plus}')
                deleted_count += 1
            else:
                logger.error(f'Failed to delete {dot_plus}: {result.get("error")}')
                print(f'Error deleting {dot_plus}: {result.get("error")}')
        else:
            logger.info(f'Skipped deletion of: {dot_plus}')
            print(f'Skipped: {dot_plus}')
            skipped_count += 1

    print(f'\nSummary:')
    print(f'  Deleted: {deleted_count}')
    print(f'  Skipped: {skipped_count}')
    logger.info(f'Remediation complete. Deleted: {deleted_count}, Skipped: {skipped_count}')


def run_remediation(axl, logger):
    """Run remediation on a single cluster."""
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

    logger.info('Searching for duplicate-ish patterns (.+ vs +)')
    duplicates = find_duplicate_patterns(route_patterns)

    if duplicates:
        print(f'\nFound {len(duplicates)} duplicate-ish pattern pairs')
        logger.info(f'Found {len(duplicates)} duplicate-ish pattern pairs')
        prompt_delete_patterns(duplicates, axl)
    else:
        logger.info('No duplicate-ish patterns found')
        print('No duplicate-ish patterns found')

    return True


def run_operation_on_cluster(basepath, cluster_data, cluster_credentials, logger):
    """Run remediation on a single cluster."""
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

        success = run_remediation(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        if success:
            print(f"✓ Completed {cluster_name} ({server})")
        return success
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, logger):
    """Run remediation on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = input('Use same credentials for all clusters? (y/n) [default: y]: ').strip().lower()
    use_same = use_same in ('', 'y', 'yes')

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
    log_file = f"../_logs/{timestamp}-remediate-duplicatish-rps.log"
    logger = setup_logger(log_file)
    logger.info("Remediate Duplicatish Route Patterns - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        response = input(f'{len(clusters_data)} clusters found. Use multiple clusters?: (y/n) ') or 'n'
        if response.lower() in ('y', 'yes'):
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

            run_remediation(axl, logger)

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

        run_remediation(axl, logger)
