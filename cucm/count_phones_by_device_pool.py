#!/usr/bin/env python3

import warnings
warnings.filterwarnings('ignore', category=Warning, module='urllib3')

"""
Count phones (devices) in CUCM grouped by Device Pool.

Usage:
    python3 count_phones_by_device_pool.py

The script is interactive and will prompt for:
    CUCM JSON File (cucm-info.json): path to the JSON file with server/login
        info (default: cucm-info.json). If the password field in that file
        is blank, you will be prompted to enter it.
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
from general import serverSetup
from setup.logger import setup_logger
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
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input(f'Enter CUCM Password for {username}: ')

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-count-phones-by-device-pool-{cucm}.log"
    logger = setup_logger(log_file)
    logger.info("Count Phones By Device Pool - Started")

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=cucm, cucm_version=version)

    logger.info('Connected to CUCM: %s (version %s)', cucm, version)

    # Ask whether to skip analog devices and CTI ports
    skip_analog_input = input('Skip analog devices and CTI ports?: (y/n) ') or 'y'
    include_analog = skip_analog_input.lower() not in ('y', 'yes')

    # Get phone counts
    rows = count_phones_by_pool(axl, logger, include_analog=include_analog)

    # Display results
    if rows is not None:
        display_results(rows, logger, include_analog=include_analog)

        # Ask whether to save to CSV
        save_csv_input = input('\nSave results to CSV?: (y/n) ') or 'n'
        if save_csv_input.lower() in ('y', 'yes'):
            csv_filename = f'phone-count-{cucm}-{time.strftime("%Y_%m_%d-%H_%M_%S")}.csv'
            csv_filepath = basepath / csv_filename
            write_results_to_csv(rows, csv_filepath, logger, include_analog=include_analog)
