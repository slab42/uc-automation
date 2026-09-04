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
    CUCM JSON File (cucm-info.json): path to the JSON file with server/login
        info (default: cucm-info.json). If the password field in that file
        is blank, you will be prompted to enter it.
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

CSV:
pattern, routePartition, newRoutePartition
3120, Phone-Line1-PT, Phone-Line2-PT

"""

from pathlib import Path
from csv import reader
import argparse
import time
import urllib3
from general import serverSetup, loggerSetup
from ucmAPI import AXL

log_filename_prefix = 'Move-DN-Partition-'

def move_dn_partition(pattern, route_partition_name, new_route_partition_name):
    """
    Move a DN to a new Route Partition. Verifies the DN exists in the
    current partition before attempting the move.

    Args:
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


def main(reverse=False):
    """
    Menu to choose single DN or list
    """
    while True:
        input_type_csv = input('Use CSV?: (y/n)') or 'n'
        if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
            use_csv(reverse)
            break
        else:
            single_dn(reverse)
            break


def single_dn(reverse=False):
    """
    Move a single DN to a new Route Partition
    """
    pattern = input('Pattern: ')
    route_partition_name = input('Current Route Partition Name: ')
    new_route_partition_name = input('New Route Partition Name: ')
    if reverse:
        route_partition_name, new_route_partition_name = new_route_partition_name, route_partition_name
    move_dn_partition(pattern, route_partition_name, new_route_partition_name)


def use_csv(reverse=False):
    """
    Bulk Move DNs from CSV
    """
    print('\nCSV Must have header row and must contain only 1 DN per row')
    print('Field Order: pattern, routePartition, newRoutePartition')
    if reverse:
        print('--reverse enabled: moving DNs from newRoutePartition back to routePartition')
    input_file = input('Enter CSV file name or full path: ') or 'mv_dnPartitions.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(my_file)
        for row in csv_file:
            pattern = row[0]
            route_partition_name = row[1]
            new_route_partition_name = row[2]
            if reverse:
                route_partition_name, new_route_partition_name = new_route_partition_name, route_partition_name
            move_dn_partition(pattern, route_partition_name, new_route_partition_name)


if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Move existing Directory Numbers to a different Route Partition.')
    parser.add_argument('--reverse', action='store_true', help='Swap partition columns, moving DNs from newRoutePartition back to routePartition')
    args = parser.parse_args()

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
    main(reverse=args.reverse)
