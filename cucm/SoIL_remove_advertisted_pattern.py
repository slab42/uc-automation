#!/usr/bin/env python3

"""
Remove Advertised Pattern individually or from a list in CSV

Usage:
    python3 remove_advertisted_pattern.py

The script is interactive and will prompt for:
    CUCM JSON File (cucm-info.json): path to the JSON file with server/login
        info (default: cucm-info.json). If the password field in that file
        is blank, you will be prompted to enter it.
    Use CSV?: (y/n): choose 'y' to bulk remove patterns from a CSV file,
        or 'n' (default) to remove a single pattern.

    If 'n' (single pattern):
        Pattern: the advertised pattern to remove

    If 'y' (CSV):
        Enter CSV file name or full path: path to the CSV file
            (default: rm_advertisedPatterns.csv)

If removal of a pattern fails and the pattern does not already start with
'+', the script automatically retries the removal with a '+' prefixed to
the pattern.

CSV:
pattern
+155585944XX



"""

from pathlib import Path
from csv import reader
import time
import urllib3
from general import serverSetup, loggerSetup
from ucmAPI import AXL

log_filename_prefix = 'Remove-Advertised-Pattern-'

def remove_pattern(pattern):
    """
    Remove an Advertised Pattern. If removal fails and the pattern
    does not already start with '+', retry with a '+' prefix.
    """
    logger.info('Removing Pattern: %s', pattern)
    result = axl.remove_advertised_patterns(pattern=pattern)
    if result.get('success'):
        logger.info(result.get('response'))
        return result
    logger.error(result.get('error'))
    if not pattern.startswith('+'):
        retry_pattern = '+' + pattern
        logger.info('Retrying Removal with Pattern: %s', retry_pattern)
        result = axl.remove_advertised_patterns(pattern=retry_pattern)
        if result.get('success'):
            logger.info(result.get('response'))
        else:
            logger.error(result.get('error'))
    return result


def main():
    """
    Menu to choose single pattern or list
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
    Remove a single Advertised Pattern
    """
    pattern = input('Pattern: ')
    remove_pattern(pattern)


def use_csv():
    """
    Bulk Remove Patterns from CSV
    """
    print('\nCSV Must have header row and must contain only 1 pattern per row')
    print('Field Order: pattern')
    input_file = input('Enter CSV file name or full path: ') or 'rm_advertisedPatterns.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(my_file)
        for row in csv_file:
            pattern = row[0]
            remove_pattern(pattern)


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
