#!/usr/bin/env python3

"""
Script checks if the DN is valid. If so then it removes Enterprise Alternate Number
and E.164 Alternate Number whether they are set or not.
Individually or from a list in CSV

CUCM Cluster: select from clusters.csv or provide manually
Credentials: checks stored credentials in credentials.env

CSV:
pattern, routePartition
3120, Phone-Line1-PT

The CSV may contain additional columns; only the pattern and routePartition
columns are used. The routePartition column is optional. If it is missing
from the CSV header, the routePartition variable below is used for every row
instead.

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictReader
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

DEFAULT_ROUTE_PARTITION = 'Phone-Line1-PT'


def remove_alt_num_line(axl, logger, pattern, route_partition_name):
    """Update DN to remove Alternate Numbers
    Args:
        axl: AXL client instance
        logger: logger instance
        pattern (string): Directory number
        route_partition_name (string): Partition
    """
    line = axl.get_Line(pattern=pattern, routePartitionName=route_partition_name)
    if line.get('success'):
        logger.info(f'{pattern} Good DN')
        enterpriseAltNum_updated = axl.update_Line(
            pattern=pattern,
            routePartitionName=route_partition_name,
            enterpriseAltNum={'numMask': None, 'isUrgent': None, 'addLocalRoutePartition': None, 'routePartition': None, 'advertiseGloballyIls': None})
        if enterpriseAltNum_updated.get('success'):
            logger.info(f'Enterprise Alternate Number removed: {enterpriseAltNum_updated.get("response")}')
        else:
            logger.error(f'Enterprise Alternate Number removal failed: {enterpriseAltNum_updated.get("error")}')

        e164AltNum_updated = axl.update_Line(
            pattern=pattern,
            routePartitionName=route_partition_name,
            e164AltNum={'numMask': None, 'isUrgent': None, 'addLocalRoutePartition': None, 'routePartition': None, 'advertiseGloballyIls': None})
        if e164AltNum_updated.get('success'):
            logger.info(f'E.164 Alternate Number removed: {e164AltNum_updated.get("response")}')
        else:
            logger.error(f'E.164 Alternate Number removal failed: {e164AltNum_updated.get("error")}')
    else:
        logger.error(f'{pattern} in {route_partition_name} does not exist.')


def run_single_alt_num_line(axl, logger):
    """
    Update single DN to remove Alternate Numbers
    """
    pattern = input('Pattern: ')
    route_partition_name = input('Route Partition Name: ')
    remove_alt_num_line(axl, logger, pattern, route_partition_name)


def run_csv_file(axl, logger, csv_file_path):
    """
    Bulk Remove Alternate Numbers from DNs in CSV
    """
    print('\nCSV Must have header row. Required columns: pattern (routePartition optional)')
    print('Additional columns are allowed and will be ignored')
    with open(csv_file_path, 'r', encoding='utf8') as my_file:
        csv_file = DictReader(my_file)
        has_pattern_col = 'pattern' in (csv_file.fieldnames or [])
        has_route_partition_col = 'routePartition' in (csv_file.fieldnames or [])
        for row in csv_file:
            pattern = row['pattern'] if has_pattern_col else row.get('dn', '')
            route_partition_name = row['routePartition'] if has_route_partition_col else DEFAULT_ROUTE_PARTITION
            if not pattern:
                logger.error('Pattern column not found and no dn fallback available')
                continue
            logger.info('Editing DN: ' + pattern + ', ' + route_partition_name)
            remove_alt_num_line(axl, logger, pattern, route_partition_name)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run alternate number removal on a single cluster."""
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
            run_single_alt_num_line(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run alternate number removal on all clusters sequentially."""
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
    log_file = f"../_logs/{timestamp}-remove-dn-entaltnum-e164altnum.log"
    logger = setup_logger(log_file)
    logger.info("Remove Dn Entaltnum E164altnum - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            # Gather operation parameters for multi-cluster
            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV Must have header row. Required columns: pattern (routePartition optional)')
                print('Additional columns are allowed and will be ignored')
                csv_file = input('Enter CSV file name or full path (default filename: rm_dnAltNumbers.csv): ') or 'rm_dnAltNumbers.csv'
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

            input_type_csv = prompt_yes_no('Use CSV?', default=False)
            if input_type_csv:
                print('\nCSV Must have header row. Required columns: pattern (routePartition optional)')
                print('Additional columns are allowed and will be ignored')
                csv_file = input('Enter CSV file name or full path (default filename: rm_dnAltNumbers.csv): ') or 'rm_dnAltNumbers.csv'
                run_csv_file(axl, logger, csv_file)
            else:
                run_single_alt_num_line(axl, logger)
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

        input_type_csv = prompt_yes_no('Use CSV?', default=False)
        if input_type_csv:
            print('\nCSV Must have header row. Required columns: pattern (routePartition optional)')
            print('Additional columns are allowed and will be ignored')
            csv_file = input('Enter CSV file name or full path (default filename: rm_dnAltNumbers.csv): ') or 'rm_dnAltNumbers.csv'
            run_csv_file(axl, logger, csv_file)
        else:
            run_single_alt_num_line(axl, logger)
