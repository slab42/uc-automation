#!/usr/bin/env python3

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

Output is displayed on screen and logged to logs/<timestamp>-count_phones_by_device_pool.log

Analog devices are filtered by device class. Excluded types include:
    - Analog Access
    - Analog Phone
    - Any device with class containing 'Analog'

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import urllib3
from general import serverSetup
from setup.logger import setup_logger
from ucmAPI import AXL

log_filename_prefix = 'count-phones-by-device-pool-'


def count_phones_by_pool(axl, logger, include_analog=False):
    """
    Query CUCM for phone counts grouped by device pool.

    Args:
        axl: AXL client instance
        logger: logger instance
        include_analog: if True, include analog devices; if False, exclude them
    """
    logger.info('=' * 70)
    logger.info('Retrieving phone counts by Device Pool')

    # Build SQL query to count devices by device pool
    sql_query = """
        SELECT dp.name as device_pool, COUNT(*) as phone_count
        FROM device d
        JOIN devicepool dp ON d.fkdevicepool = dp.pkid
        WHERE d.tkclass NOT IN ('VirtualDevice', 'ConfiguredDevice', 'Messaging')
    """

    # Add analog filter if requested
    if not include_analog:
        sql_query += """
        AND d.tkclass NOT IN (
            'GatewayEndpointAnalogAccess',
            'AnalogPhone',
            'AnalogAccessDevice'
        )
        AND d.tkmodel NOT LIKE '%Analog%'
        """

    sql_query += " GROUP BY dp.name ORDER BY dp.name"

    logger.debug('Executing SQL query: %s', sql_query.replace('\n', ' '))

    result = axl.execute_sql_query(sql_query)
    if not result.get('success'):
        logger.error('Failed to retrieve phone counts: %s', result.get('error'))
        return None

    rows = result.get('response', [])
    if not rows:
        logger.warning('No devices found in any device pools')
        return []

    # Convert single row to list if needed
    if not isinstance(rows, list):
        rows = [rows]

    logger.info('Successfully retrieved phone count data from %d device pools', len(rows))
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
        print('Phone Count by Device Pool (Including Analog Devices)')
    else:
        print('Phone Count by Device Pool (Analog Devices Excluded)')
    print('=' * 70)
    print(f'{"Device Pool Name":<40} {"Phone Count":>15}')
    print('-' * 70)

    # Log header
    logger.info('=' * 70)
    if include_analog:
        logger.info('Phone Count by Device Pool (Including Analog Devices)')
    else:
        logger.info('Phone Count by Device Pool (Analog Devices Excluded)')
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


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input(f'Enter CUCM Password for {username}: ')

    # Setup Logging
    logger = setup_logger(basepath / 'logs' / (log_filename_prefix + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log'))

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=cucm, cucm_version=version)

    logger.info('Connected to CUCM: %s (version %s)', cucm, version)

    # Ask whether to include analog devices
    include_analog_input = input('Include Analog Devices?: (y/n) ') or 'n'
    include_analog = include_analog_input.lower() in ('y', 'yes')

    # Get phone counts
    rows = count_phones_by_pool(axl, logger, include_analog=include_analog)

    # Display results
    if rows is not None:
        display_results(rows, logger, include_analog=include_analog)
