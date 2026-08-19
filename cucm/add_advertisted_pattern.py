#!/usr/bin/env python3

"""
Add Advertised Pattern individually or from a list in CSV

CSV:
description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend
Test DIDs,+155585944XX,+E.164 Number,Use pattern,0,

patternType: +E.164 Number, Enterprise Number
hostedRoutePSTNRule: No PSTN, Use pattern, Specify


"""

from pathlib import Path
from csv import reader
import time
import urllib3
from general import serverSetup, loggerSetup
from ucmAPI import AXL

log_filename_prefix = 'Add-Advertised-Pattern-'

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
            single_pattern()
            break


def single_pattern():
    """
    Add a single Advertised Pattern
    """
    description = input('Description: ')
    pattern = input('Pattern: ')
    patternType = input('Pattern Type: ')
    hostedRoutePSTNRule = input('Route PSTN Rule: (or hit enter for - No PSTN)') or 'No PSTN'
    pstnFailStrip = input('PSTN Digit Strip: (or hit enter for None)') or ''
    if pstnFailStrip == '':
        pstnFailStrip = '0'
    pstnFailPrepend = input('PSTN Prepend: (or hit enter for None)') or ''
    logger.info('Adding Pattern: %s as %s', pattern, patternType)
    result = axl.add_advertised_patterns(description=description, 
                                            pattern=pattern, 
                                            patternType=patternType, 
                                            hostedRoutePSTNRule=hostedRoutePSTNRule, 
                                            pstnFailStrip=pstnFailStrip,
                                            pstnFailPrepend=pstnFailPrepend)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))


def use_csv():
    """
    Bulk Import Patterns from CSV
    """
    print('\nCSV Must have header row and must contain only 1 pattern settings per row')
    print('Field Order: description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend')
    input_file = input('Enter CSV file name or full path: ') or 'advertisedPatterns.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(my_file)
        for row in csv_file:
            description = row[0]
            pattern = row[1]
            patternType = row[2]
            hostedRoutePSTNRule = row[3]
            pstnFailStrip = row[4]
            pstnFailPrepend = row[5]
            logger.info('Adding Pattern: %s as %s', pattern, patternType)
            result = axl.add_advertised_patterns(description=description, 
                                            pattern=pattern, 
                                            patternType=patternType, 
                                            hostedRoutePSTNRule=hostedRoutePSTNRule, 
                                            pstnFailStrip=pstnFailStrip,
                                            pstnFailPrepend=pstnFailPrepend)
            if result.get('success'):
                logger.info(result.get('response'))
            else:
                logger.error(result.get('error'))


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')

    # Setup Logging
    logger = loggerSetup(basepath / 'logs' / (basepath / 'logs' / (log_filename_prefix + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log')))

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username,password=password,wsdl=wsdl,cucm=cucm,cucm_version=version)

    # Calling the main function
    main()
