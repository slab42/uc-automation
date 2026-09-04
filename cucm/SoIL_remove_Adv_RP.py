#!/usr/bin/env python3

"""
Remove Advertised Pattern and matching Route Pattern individually or from a list in CSV

Uses the same CSV format as SoIL_add_AdvP_RP.py:

CSV:
pattern, departmentName
+155585944XX,Sales

departmentName (column 2) is ignored for removal but may be present in the CSV.

Patterns are formatted the same way they were added: 10 digit numbers get a +1
prefix for the Advertised Pattern and \\+1 for the Route Pattern.
"""

from pathlib import Path
from csv import reader
import time
import urllib3
from general import serverSetup, loggerSetup
from ucmAPI import AXL

log_filename_prefix = 'Remove-AdvP-RP-'

routePartition = 'Soil-Enterprise_PT'


def format_advertised_pattern(pattern):
    """
    Format a number for the Advertised Pattern. 10 digit numbers get a +1 prefix.
    11 digit numbers starting with 1 get a + prefix.
    """
    value = pattern.strip()
    if value.isdigit() and len(value) == 10:
        return '+1' + value
    if value.isdigit() and len(value) == 11 and value.startswith('1'):
        return '+' + value
    return value


def format_route_pattern(pattern):
    """
    Format a number for the Route Pattern. Numbers already in +1 format get a
    \\ prefix. 10 digit numbers get a \\+1 prefix.
    """
    value = pattern.strip()
    if value.startswith('+1'):
        return '\\' + value
    if value.isdigit() and len(value) == 10:
        return '\\+1' + value
    return value


def remove_advertised_pattern(pattern):
    """
    Remove an Advertised Pattern for the given number
    """
    formattedPattern = format_advertised_pattern(pattern)
    logger.info('Removing Advertised Pattern: %s', formattedPattern)
    result = axl.remove_advertised_patterns(pattern=formattedPattern)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))


def remove_route_pattern(pattern):
    """
    Remove a Route Pattern for the given number
    """
    formattedPattern = format_route_pattern(pattern)
    logger.info('Removing Route Pattern: %s in partition %s', formattedPattern, routePartition)
    result = axl.remove_Route_Pattern(pattern=formattedPattern,
                                        routePartitionName=routePartition)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))


def main():
    """
    Menu to choose single number or list
    """
    while True:
        input_type_csv = input('Use CSV?: (y/n)') or 'n'
        if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
            use_csv()
            break
        else:
            single_pattern()
            break


def single_pattern():
    """
    Remove a single Advertised Pattern and matching Route Pattern
    """
    pattern = input('Pattern (Number): ')
    remove_advertised_pattern(pattern)
    remove_route_pattern(pattern)


def use_csv():
    """
    Bulk Remove numbers from CSV, removing the Advertised Pattern and Route Pattern for each
    """
    print('\nCSV Must have header row')
    print('Field Order: pattern, departmentName (departmentName is ignored)')
    input_file = input('Enter CSV file name or full path: ') or 'SoIL_AdvP_RP.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(csv_file)
        for row in csv_file:
            pattern = row[0].strip()
            remove_advertised_pattern(pattern)
            remove_route_pattern(pattern)


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input('Enter CUCM Password for ' + username + ':')

    # Setup Logging
    logger = loggerSetup(basepath / 'logs' / (basepath / 'logs' / (log_filename_prefix + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log')))

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username,password=password,wsdl=wsdl,cucm=cucm,cucm_version=version)

    # Calling the main function
    main()
