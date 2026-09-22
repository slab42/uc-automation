#!/usr/bin/env python3

"""
Remove Advertised Pattern individually or from a list in CSV

Usage:
    python3 remove_advertisted_pattern.py

The script is interactive and will prompt for:
    CUCM Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use CSV?: (y/n): choose 'y' to bulk remove patterns from a CSV file,
        or 'n' (default) to remove a single pattern.

    If 'n' (single pattern):
        Pattern: the advertised pattern to remove

    If 'y' (CSV):
        Enter CSV file name or full path: path to the CSV file
            (default: rm_advertisedPatterns.csv)

If removal of a pattern fails and the pattern does not already start with
'+', the script automatically retries the removal with a '+' prefixed to
the pattern.

CSV format (pattern):
+155585944XX

The CSV may contain additional columns; only the "pattern" column is used.

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictReader
from datetime import datetime
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


def remove_pattern(axl, logger, pattern):
    """
    Remove an Advertised Pattern. If removal fails and the pattern
    does not already start with '+', retry with a '+' prefix.
    """
    logger.info('Removing Pattern: %s', pattern)
    result = axl.remove_advertised_patterns(pattern=pattern)
    if result.get('success'):
        logger.info(result.get('response'))
        return result
    logger.error(result.get('error'))
    if not pattern.startswith('+'):
        retry_pattern = '+' + pattern
        logger.info('Retrying Removal with Pattern: %s', retry_pattern)
        result = axl.remove_advertised_patterns(pattern=retry_pattern)
        if result.get('success'):
            logger.info(result.get('response'))
        else:
            logger.error(result.get('error'))
    return result


def run_single_pattern(axl, logger):
    """
    Remove a single Advertised Pattern
    """
    pattern = input('Pattern: ')
    remove_pattern(axl, logger, pattern)


def run_csv_file(axl, logger, csv_file_path):
    """
    Bulk Remove Patterns from CSV
    """
    print('\nCSV Must have header row and must contain only 1 pattern per row')
    print('Field Order: pattern')
    with open(csv_file_path, 'r', encoding='utf8') as my_file:
        csv_file = DictReader(my_file)
        for row in csv_file:
            pattern = row['pattern']
            remove_pattern(axl, logger, pattern)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run pattern removal on a single cluster."""
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

        op_type = operation_params.get('type')
        if op_type == 'csv':
            run_csv_file(axl, logger, operation_params['csv_file'])
        else:  # single
            run_single_pattern(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run pattern removal on all clusters sequentially."""
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
    log_file = f"../_logs/{timestamp}-remove-advertisted-pattern.log"
    logger = setup_logger(log_file)
    logger.info("Remove Advertisted Pattern - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            # Gather operation parameters for multi-cluster
            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV Must have header row and must contain only 1 pattern per row')
                print('Field Order: pattern')
                csv_file = input('Enter CSV file name or full path: ') or 'rm_advertisedPatterns.csv'
                operation_params = {'type': 'csv', 'csv_file': csv_file}
            else:
                operation_params = {'type': 'single'}
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

            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV Must have header row and must contain only 1 pattern per row')
                print('Field Order: pattern')
                csv_file = input('Enter CSV file name or full path: ') or 'rm_advertisedPatterns.csv'
                run_csv_file(axl, logger, csv_file)
            else:
                run_single_pattern(axl, logger)
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

        use_csv = prompt_yes_no('Use CSV?', default=False)
        if use_csv:
            print('\nCSV Must have header row and must contain only 1 pattern per row')
            print('Field Order: pattern')
            csv_file = input('Enter CSV file name or full path: ') or 'rm_advertisedPatterns.csv'
            run_csv_file(axl, logger, csv_file)
        else:
            run_single_pattern(axl, logger)
