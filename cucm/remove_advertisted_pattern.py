#!/usr/bin/env python3

"""
Remove Advertised Pattern individually or from a list in CSV

Usage:
    python3 remove_advertisted_pattern.py

The script is interactive and will prompt for:
    CUCM Cluster: select from clusters.csv or provide manually
    Credentials: checks stored credentials in credentials.env
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

CSV format (pattern):
+155585944XX

The CSV may contain additional columns; only the "pattern" column is used.

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictReader
from datetime import datetime
import urllib3
from setup.logger import setup_logger
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL


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
        csv_file = DictReader(my_file)
        for row in csv_file:
            pattern = row['pattern']
            remove_pattern(pattern)


if __name__ == '__main__':
    basepath = Path.cwd()

    # Load cluster information
    cluster = get_object_for_single_operation(basepath, 'CUCM')
    if not cluster:
        print("Error: Unable to load cluster information")
        sys.exit(1)

    # Load credentials
    username, password = load_credentials('CUCM', cluster['name'])

    cucm = cluster['server']
    version = cluster['version']

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remove-advertisted-pattern-{cucm}.log"
    logger = setup_logger(log_file)
    logger.info("Remove Advertisted Pattern - Started")

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=cucm, cucm_version=version)

    # Calling the main function
    main()
