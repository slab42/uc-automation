#!/usr/bin/env python3

"""
Move existing Directory Numbers to a different Route Partition,
individually or from a list in CSV.

Usage:
    python3 move_DN_partition.py [--reverse]

    --reverse: Swap the partition columns, moving each DN from
        newRoutePartition back to routePartition (right column to left).
        Useful for undoing a previous run.

The script is interactive and will prompt for:
    CUCM Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Use CSV?: (y/n): choose 'y' to bulk move DNs from a CSV file,
        or 'n' (default) to move a single DN.

    If 'n' (single DN):
        Pattern: the DN to move
        Current Route Partition Name: the partition the DN currently lives in
        New Route Partition Name: the partition to move the DN into

    If 'y' (CSV):
        Enter CSV file name or full path: path to the CSV file
            (default: mv_dnPartitions.csv)

Before moving, the script verifies the DN exists in the current partition.
If it does not, the move is skipped and logged as an error.

CSV format (pattern, routePartition, newRoutePartition):
3120, Phone-Line1-PT, Phone-Line2-PT

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader
import argparse
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


def move_dn_partition(axl, logger, pattern, route_partition_name, new_route_partition_name):
    """
    Move a DN to a new Route Partition. Verifies the DN exists in the
    current partition before attempting the move.

    Args:
        axl: AXL client instance
        logger: logger instance
        pattern (string): Directory number
        route_partition_name (string): Current partition
        new_route_partition_name (string): Partition to move the DN into
    """
    line = axl.get_Line(pattern=pattern, routePartitionName=route_partition_name)
    if not line.get('success'):
        logger.error('%s in %s does not exist.', pattern, route_partition_name)
        return line

    logger.info('Moving %s from %s to %s', pattern, route_partition_name, new_route_partition_name)
    result = axl.update_Line(
        pattern=pattern,
        routePartitionName=route_partition_name,
        newRoutePartitionName=new_route_partition_name)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))
    return result


def run_single_dn(axl, logger, reverse=False):
    """
    Move a single DN to a new Route Partition
    """
    pattern = input('Pattern: ')
    route_partition_name = input('Current Route Partition Name: ')
    new_route_partition_name = input('New Route Partition Name: ')
    if reverse:
        route_partition_name, new_route_partition_name = new_route_partition_name, route_partition_name
    move_dn_partition(axl, logger, pattern, route_partition_name, new_route_partition_name)


def run_csv_file(axl, logger, csv_file_path, reverse=False):
    """
    Bulk Move DNs from CSV
    """
    print('\nCSV Must have header row and must contain only 1 DN per row')
    print('Field Order: pattern, routePartition, newRoutePartition')
    if reverse:
        print('--reverse enabled: moving DNs from newRoutePartition back to routePartition')
    with open(csv_file_path, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(my_file)
        for row in csv_file:
            pattern = row[0]
            route_partition_name = row[1]
            new_route_partition_name = row[2]
            if reverse:
                route_partition_name, new_route_partition_name = new_route_partition_name, route_partition_name
            move_dn_partition(axl, logger, pattern, route_partition_name, new_route_partition_name)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run DN partition move on a single cluster."""
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
        reverse = operation_params.get('reverse', False)
        if op_type == 'csv':
            run_csv_file(axl, logger, operation_params['csv_file'], reverse=reverse)
        else:  # single
            run_single_dn(axl, logger, reverse=reverse)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run DN partition move on all clusters sequentially."""
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
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Move existing Directory Numbers to a different Route Partition.')
    parser.add_argument('--reverse', action='store_true', help='Swap partition columns, moving DNs from newRoutePartition back to routePartition')
    args = parser.parse_args()

    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-move-dn-partition.log"
    logger = setup_logger(log_file)
    logger.info("Move Dn Partition - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            # Gather operation parameters for multi-cluster
            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV Must have header row and must contain only 1 DN per row')
                print('Field Order: pattern, routePartition, newRoutePartition')
                csv_file = input('Enter CSV file name or full path: ') or 'mv_dnPartitions.csv'
                operation_params = {'type': 'csv', 'csv_file': csv_file, 'reverse': args.reverse}
            else:
                operation_params = {'type': 'single', 'reverse': args.reverse}
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
                print('\nCSV Must have header row and must contain only 1 DN per row')
                print('Field Order: pattern, routePartition, newRoutePartition')
                csv_file = input('Enter CSV file name or full path: ') or 'mv_dnPartitions.csv'
                run_csv_file(axl, logger, csv_file, reverse=args.reverse)
            else:
                run_single_dn(axl, logger, reverse=args.reverse)
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
            print('\nCSV Must have header row and must contain only 1 DN per row')
            print('Field Order: pattern, routePartition, newRoutePartition')
            csv_file = input('Enter CSV file name or full path: ') or 'mv_dnPartitions.csv'
            run_csv_file(axl, logger, csv_file, reverse=args.reverse)
        else:
            run_single_dn(axl, logger, reverse=args.reverse)
