#!/usr/bin/env python3

"""
Add Advertised Pattern and matching Route Pattern individually or from a list in CSV

CSV:
pattern, departmentName
+155585944XX,Sales

departmentName (column 2) is optional. If not supplied via --dept and not present in
the CSV, the script will prompt for it during execution.

10 digit numbers are automatically prefixed with +1 for the Advertised Pattern and
\\+1 for the Route Pattern.
"""

from pathlib import Path
from csv import reader
import argparse
import time
import urllib3
from general import serverSetup, loggerSetup
from ucmAPI import AXL

log_filename_prefix = 'Add-AdvP-RP-'

patternType = 'Enterprise Number'
hostedRoutePSTNRule = 'No PSTN'
pstnFailStrip = '0'
pstnFailPrepend = ""

routePartition = 'Soil-Enterprise_PT'
gatewayRouteList = 'Soil-WebexCalling'

promptedDepartmentName = None


def get_department_name(csv_value=''):
    """
    Determine departmentName using precedence: --dept argument, CSV column, prompt
    """
    global promptedDepartmentName
    if departmentName:
        return departmentName
    if csv_value:
        return csv_value
    if promptedDepartmentName is None:
        promptedDepartmentName = input('Department Name: ')
    return promptedDepartmentName


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


def add_advertised_pattern(pattern, dept):
    """
    Add an Advertised Pattern for the given number
    """
    formattedPattern = format_advertised_pattern(pattern)
    description = dept + " Webex Calling " + formattedPattern
    logger.info('Adding Advertised Pattern: %s as %s', formattedPattern, patternType)
    result = axl.add_advertised_patterns(description=description,
                                            pattern=formattedPattern,
                                            patternType=patternType,
                                            hostedRoutePSTNRule=hostedRoutePSTNRule,
                                            pstnFailStrip=pstnFailStrip,
                                            pstnFailPrepend=pstnFailPrepend)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))


def add_route_pattern(pattern, dept):
    """
    Add a Route Pattern for the given number
    """
    formattedPattern = format_route_pattern(pattern)
    description = dept + " DID to Webex Calling"
    logger.info('Adding Route Pattern: %s in partition %s', formattedPattern, routePartition)
    result = axl.add_Route_Pattern(pattern=formattedPattern,
                                    description=description,
                                    routePartitionName=routePartition,
                                    gatewayRouteList=gatewayRouteList)
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
    Add a single Advertised Pattern and matching Route Pattern
    """
    pattern = input('Pattern (Number): ')
    dept = get_department_name()
    add_advertised_pattern(pattern, dept)
    add_route_pattern(pattern, dept)


def use_csv():
    """
    Bulk Import numbers from CSV, adding an Advertised Pattern and Route Pattern for each
    """
    print('\nCSV Must have header row')
    print('Field Order: pattern, departmentName (departmentName is optional)')
    input_file = input('Enter CSV file name or full path: ') or 'SoIL_AdvP_RP.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(csv_file)
        for row in csv_file:
            pattern = row[0].strip()
            csv_dept = row[1].strip() if len(row) > 1 else ''
            dept = get_department_name(csv_dept)
            add_advertised_pattern(pattern, dept)
            add_route_pattern(pattern, dept)


if __name__ == '__main__':
    # Parse runtime arguments
    argParser = argparse.ArgumentParser(description='Add Advertised Pattern and Route Pattern in CUCM')
    argParser.add_argument('--dept', dest='dept', default=None, help='Department name to use for descriptions')
    args = argParser.parse_args()
    departmentName = args.dept

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
