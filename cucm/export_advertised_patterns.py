#!/usr/bin/env python3

"""
Export Advertised Patterns from CUCM to a CSV file

Connects to CUCM, retrieves all advertised patterns, and exports them
to a CSV file with date and time in the filename.

CSV Output Format:
description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictWriter
import time
import urllib3
from general import serverSetup
from setup.on_prem.logger import setup_logger
from ucmAPI import AXL

log_filename_prefix = 'Export-Advertised-Patterns-'


def export_patterns_to_csv(patterns):
    """
    Export advertised patterns to a CSV file with timestamp

    Args:
        patterns (list): List of advertised pattern dictionaries
    """
    timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
    output_filename = f'advertised_patterns-{timestamp}.csv'

    if not patterns:
        logger.warning('No advertised patterns to export')
        return

    try:
        with open(output_filename, 'w', newline='', encoding='utf8') as csvfile:
            fieldnames = ['description', 'pattern', 'patternType', 'hostedRoutePSTNRule',
                         'pstnFailStrip', 'pstnFailPrepend']
            writer = DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for pattern_obj in patterns:
                row = {
                    'description': pattern_obj.get('description', ''),
                    'pattern': pattern_obj.get('pattern', ''),
                    'patternType': pattern_obj.get('patternType', ''),
                    'hostedRoutePSTNRule': pattern_obj.get('hostedRoutePSTNRule', ''),
                    'pstnFailStrip': pattern_obj.get('pstnFailStrip', ''),
                    'pstnFailPrepend': pattern_obj.get('pstnFailPrepend', ''),
                }
                writer.writerow(row)

            logger.info(f'Successfully exported {len(patterns)} advertised patterns to {output_filename}')
            print(f'\nAdvertised patterns exported to: {output_filename}')
    except IOError as e:
        logger.error(f'Error writing to CSV file: {e}')
        print(f'Error writing CSV file: {e}')


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input('Enter CUCM Password for ' + username + ':')

    # Setup Logging
    logger = setup_logger(basepath / 'logs' / (log_filename_prefix + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log')))

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=cucm, cucm_version=version)

    # Get all advertised patterns
    logger.info('Fetching advertised patterns from CUCM')
    result = axl.list_advertised_patterns()

    if result.get('success'):
        response = result.get('response', [])
        if not response or response == '':
            patterns = []
        elif isinstance(response, list):
            patterns = response
        else:
            patterns = [response]
        logger.info(f'Retrieved {len(patterns)} advertised patterns')
        export_patterns_to_csv(patterns)
    else:
        logger.error(f'Failed to retrieve advertised patterns: {result.get("error")}')
        print(f'Error: {result.get("error")}')
