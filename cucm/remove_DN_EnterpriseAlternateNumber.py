#!/usr/bin/env python3

"""
Script checks if the DN is valid.  If so then it removes Enterprise Alternate Number whether it is set or not.
Individually or from a list in CSV

CSV:
dn, routePartition
3120, Phone-Line1-PT

The routePartition column is optional. If it is missing from the CSV
header, the routePartition variable below is used for every row instead.

"""

from pathlib import Path
from csv import DictReader
import time
import urllib3
from general import serverSetup, loggerSetup
from ucmAPI import AXL

routePartition = ''


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
            remove_Single_enterpriseAltNum_line()
            break


def remove_enterpriseAltNum_line(pattern, route_partition_name,):
    """Update DN to remove Alternate Number
    Args:
        pattern (string): Directory number
        route_partition_name (string): Partition
    """    
    line = axl.get_Line(pattern = pattern, routePartitionName = route_partition_name)
    if line.get('success'):
        logger.info(f'{pattern} Good DN')
        enterpriseAltNum_updated = axl.update_Line(
            pattern = pattern,
            routePartitionName = route_partition_name,
            enterpriseAltNum = {'numMask': None, 'isUrgent': None, 'addLocalRoutePartition': None, 'routePartition': None, 'advertiseGloballyIls': None})
        if enterpriseAltNum_updated.get('success'):
            logger.info(enterpriseAltNum_updated.get('response'))
        else:
            logger.error(enterpriseAltNum_updated.get('error'))
    else:
        logger.error(f'{pattern} in {route_partition_name} does not exist.')


def remove_Single_enterpriseAltNum_line():
    """
    Update single DN to remove Alternate Number
    """    
    pattern = input('Pattern: ')
    route_partition_name = input('Route Partition Name: ')
    remove_enterpriseAltNum_line(pattern, route_partition_name)


def use_csv():
    """
    Bulk Import DNs from CSV
    """
    print('\nCSV Must have header row and must contain only 1 pattern settings per row')
    print('Field Order: dn, routePartition')
    input_file = input('Enter CSV file name or full path (default filename: rm_dnEnterpriseAltNumbers.csv): ') or 'rm_dnEnterpriseAltNumbers.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = DictReader(my_file)
        has_route_partition_col = 'routePartition' in (csv_file.fieldnames or [])
        for row in csv_file:
            pattern = row['dn']
            route_partition_name = row['routePartition'] if has_route_partition_col else routePartition
            logger.info('Editing DN: ' + pattern + ', ' + route_partition_name)
            result = remove_enterpriseAltNum_line(pattern, route_partition_name)


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input('Enter CUCM Password for ' + username + ':')
        
    # Setup Logging
    logger = loggerSetup(basepath / 'logs' / (basepath / 'logs' / ('Remove_DN_AlternateNumber-' + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log')))

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username,password=password,wsdl=wsdl,cucm=cucm,cucm_version=version)

    ### Calling the main function
    main()



