#!/usr/bin/env python3

import warnings
warnings.filterwarnings('ignore', category=Warning, module='urllib3')

"""
Count phones (devices) in CUCM grouped by Device Pool.

Usage:
    python3 count_phones_by_device_pool.py

The script is interactive and will prompt for:
    CUCM Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
    Include Analog Devices?: (y/n): choose 'y' to include analog access
        devices in the count, or 'n' (default) to exclude them.

The script retrieves all phones from CUCM via AXL API, groups them by device
pool, and optionally filters out analog devices and CTI ports before counting.

Output is displayed on screen and logged to logs/<timestamp>-count_phones_by_device_pool.log

When excluding analog devices, the script filters out:
    - Products containing 'Analog' in the name
    - Analog Access
    - Analog Phone
    - Gateway Endpoint Analog Access
    - Products containing 'CTI' in the name (CTI ports, CTI OS ports)

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import time
import urllib3
import csv
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from ucmAPI import AXL



def count_phones_by_pool(axl, logger, include_analog=False):
    """
    Query CUCM for phone counts grouped by device pool.
    Uses AXL API to retrieve all phones and groups by device pool.

    Args:
        axl: AXL client instance
        logger: logger instance
        include_analog: if True, include analog and CTI devices; if False, exclude them
    """
    logger.info('=' * 70)
    logger.info('Retrieving phone counts by Device Pool')

    # Get all phones from CUCM
    logger.debug('Fetching all phones from CUCM...')
    phones_result = axl.list_Phone()
    if not phones_result.get('success'):
        logger.error('Failed to retrieve phones: %s', phones_result.get('error'))
        return None

    phones = phones_result.get('response', [])
    if not phones:
        logger.warning('No phones found in CUCM')
        return []

    # Convert single phone to list if needed
    if not isinstance(phones, list):
        phones = [phones]

    logger.info('Retrieved %d total phones from CUCM', len(phones))

    # Group phones by device pool and count
    pool_counts = {}
    excluded_analog = 0

    for phone in phones:
        # Get device pool (may be missing for some devices)
        pool_name = phone.get('devicePoolName')

        # Handle OrderedDict response from zeep
        if pool_name and hasattr(pool_name, 'get'):
            pool_name = pool_name.get('_value_1') or str(pool_name)

        # Convert to string if not already
        if pool_name:
            pool_name = str(pool_name)
        else:
            pool_name = 'Unknown/Unassigned'

        # Check if device is analog or CTI port (by product/class)
        product = str(phone.get('product', '')).lower()
        is_analog = ('analog' in product or 'cti' in product or
                    product in ('gatewayendpointanalogaccess', 'analogphone', 'analogaccessdevice'))

        if is_analog and not include_analog:
            excluded_analog += 1
            logger.debug('Excluding analog/CTI device: %s (product: %s)',
                        phone.get('name'), phone.get('product'))
            continue

        # Count this phone
        if pool_name not in pool_counts:
            pool_counts[pool_name] = 0
        pool_counts[pool_name] += 1

    # Convert to list of dicts and sort by pool name
    rows = [{'device_pool': pool, 'phone_count': count}
            for pool, count in sorted(pool_counts.items())]

    if excluded_analog > 0:
        logger.info('Excluded %d analog/CTI devices from count', excluded_analog)

    logger.info('Successfully grouped phones into %d device pools', len(rows))
    return rows


def display_results(rows, logger, include_analog=False):
    """
    Display phone count results in formatted table.

    Args:
        rows: list of result dicts with 'device_pool' and 'phone_count' keys
        logger: logger instance
        include_analog: whether analog devices were included in the count
    """
    if not rows:
        return

    # Display header
    print('\n')
    print('=' * 70)
    if include_analog:
        print('Phone Count by Device Pool (Including Analog & CTI Devices)')
    else:
        print('Phone Count by Device Pool (Analog & CTI Devices Excluded)')
    print('=' * 70)
    print(f'{"Device Pool Name":<40} {"Phone Count":>15}')
    print('-' * 70)

    # Log header
    logger.info('=' * 70)
    if include_analog:
        logger.info('Phone Count by Device Pool (Including Analog & CTI Devices)')
    else:
        logger.info('Phone Count by Device Pool (Analog & CTI Devices Excluded)')
    logger.info('=' * 70)
    logger.info('%-40s %15s', 'Device Pool Name', 'Phone Count')
    logger.info('-' * 70)

    # Display rows and calculate total
    total_phones = 0
    for row in rows:
        pool_name = row.get('device_pool', 'Unknown')
        phone_count = int(row.get('phone_count', 0))
        total_phones += phone_count

        print(f'{pool_name:<40} {phone_count:>15,}')
        logger.info('%-40s %15s', pool_name, f'{phone_count:,}')

    # Display total
    print('-' * 70)
    print(f'{"TOTAL":<40} {total_phones:>15,}')
    print('=' * 70)
    print()

    logger.info('-' * 70)
    logger.info('%-40s %15s', 'TOTAL', f'{total_phones:,}')
    logger.info('=' * 70)
    logger.info('Phone count operation completed successfully')


def run_report(axl, logger, server, include_analog=False):
    """Run phone count report on a single cluster."""
    rows = count_phones_by_pool(axl, logger, include_analog=include_analog)
    if rows is not None:
        display_results(rows, logger, include_analog=include_analog)

        # Ask whether to save to CSV
        save_csv = prompt_yes_no('\nSave results to CSV?', default=False)
        if save_csv:
            timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
            if server:
                csv_filename = f'phone-count-{server}-{timestamp}.csv'
            else:
                csv_filename = f'phone-count-{timestamp}.csv'
            write_results_to_csv(rows, csv_filename, logger, include_analog=include_analog)
    return True


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run phone count operation on a single cluster."""
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

        include_analog = operation_params.get('include_analog', False)
        success = run_report(axl, logger, server, include_analog=include_analog)

        logger.info('Completed cluster: %s', cluster_name)
        if success:
            print(f"✓ Completed {cluster_name} ({server})")
        return success
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run phone count on all clusters sequentially."""
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


def write_results_to_csv(rows, filepath, logger, include_analog=False):
    """
    Write phone count results to CSV file.

    Args:
        rows: list of result dicts with 'device_pool' and 'phone_count' keys
        filepath: path to write CSV file
        logger: logger instance
        include_analog: whether analog/CTI devices were included in the count
    """
    try:
        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)

            # Write header with filter info
            filter_status = 'Including Analog & CTI Devices' if include_analog else 'Excluding Analog & CTI Devices'
            writer.writerow(['Phone Count by Device Pool'])
            writer.writerow([f'Filter: {filter_status}'])
            writer.writerow([f'Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow([])  # Blank row

            # Write column headers
            writer.writerow(['Device Pool Name', 'Phone Count'])

            # Write data rows
            total_phones = 0
            for row in rows:
                pool_name = row.get('device_pool', '')
                phone_count = int(row.get('phone_count', 0))
                total_phones += phone_count
                writer.writerow([pool_name, phone_count])

            # Write total row
            writer.writerow([])  # Blank row
            writer.writerow(['TOTAL', total_phones])

        logger.info('Results saved to CSV: %s', filepath)
        print(f'\nResults saved to: {filepath}')
    except Exception as e:
        logger.error('Failed to write CSV file: %s', str(e))
        print(f'Error saving CSV: {e}')


if __name__ == '__main__':
    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-count-phones-by-device-pool.log"
    logger = setup_logger(log_file)
    logger.info("Count Phones By Device Pool - Started")

    # Ask whether to skip analog devices and CTI ports
    skip_analog = prompt_yes_no('Skip analog devices and CTI ports?', default=True)
    include_analog = not skip_analog
    operation_params = {'include_analog': include_analog}

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
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

            logger.info('Connected to CUCM: %s (version %s)', server, version)
            run_report(axl, logger, server, include_analog=include_analog)
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

        logger.info('Connected to CUCM: %s (version %s)', server, version)
        run_report(axl, logger, server, include_analog=include_analog)
