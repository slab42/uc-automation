#!/usr/bin/env python3

"""
Script checks if the DN is valid. If so then it removes Enterprise Alternate Number
and E.164 Alternate Number whether they are set or not.
Individually or from a list in CSV

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
import time
import urllib3
from general import serverSetup
from setup.logger import setup_logger
from ucmAPI import AXL

routePartition = 'Phone-Line1-PT'


def main():
    """
    Menu to choose single phone or list
    """
    while True:
        input_type_csv = input('Use CSV?: (y/n)') or 'n'
        if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
            use_csv()
            break
        else:
            remove_single_alt_num_line()
            break


def remove_alt_num_line(pattern, route_partition_name):
    """Update DN to remove Alternate Numbers
    Args:
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


def remove_single_alt_num_line():
    """
    Update single DN to remove Alternate Numbers
    """
    pattern = input('Pattern: ')
    route_partition_name = input('Route Partition Name: ')
    remove_alt_num_line(pattern, route_partition_name)


def use_csv():
    """
    Bulk Remove Alternate Numbers from DNs in CSV
    """
    print('\nCSV Must have header row. Required columns: pattern (routePartition optional)')
    print('Additional columns are allowed and will be ignored')
    input_file = input('Enter CSV file name or full path (default filename: rm_dnAltNumbers.csv): ') or 'rm_dnAltNumbers.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = DictReader(my_file)
        has_pattern_col = 'pattern' in (csv_file.fieldnames or [])
        has_route_partition_col = 'routePartition' in (csv_file.fieldnames or [])
        for row in csv_file:
            pattern = row['pattern'] if has_pattern_col else row.get('dn', '')
            route_partition_name = row['routePartition'] if has_route_partition_col else routePartition
            if not pattern:
                logger.error('Pattern column not found and no dn fallback available')
                continue
            logger.info('Editing DN: ' + pattern + ', ' + route_partition_name)
            result = remove_alt_num_line(pattern, route_partition_name)


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input('Enter CUCM Password for ' + username + ':')

    # Setup Logging
    logger = setup_logger(basepath / 'logs' / ('Remove_DN_AltNumbers-' + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log')))

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username,password=password,wsdl=wsdl,cucm=cucm,cucm_version=version)

    ### Calling the main function
    main()
