#!/usr/bin/env python3

"""
Update phone load on phones in CUCM based on phone model.

CSV:
phone
SEP0123456789AB

or

mac
0123456789AB

The CSV must contain either 'phone' (with SEP prefix) or 'mac' (12-digit MAC address)
column. If 'mac' is provided without SEP prefix, the script will add it.

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictReader
from datetime import datetime
import time
import urllib3
import getpass
from general import serverSetup
from setup.logger import setup_logger
from ucmAPI import AXL



def format_phone_identifier(identifier):
    """Format phone identifier with SEP prefix if needed
    Args:
        identifier (string): Phone identifier (MAC address or phone name)
    Returns:
        formatted identifier with SEP prefix
    """
    identifier = identifier.strip()
    if len(identifier) == 12 and identifier.isalnum():
        return f'SEP{identifier}'
    if identifier.startswith('SEP') and len(identifier) == 15:
        return identifier
    return identifier


def get_phone_load_for_model(model):
    """Determine Phone Load based on phone model
    Args:
        model (string): Phone model
    Returns:
        Phone Load string or None
    """
    if not model:
        return None

    if '7832' in model:
        return 'sip7832.14-4-1-0001-36'
    elif '8832' in model:
        return 'sip8832.14-4-1-0001-36'
    elif '8845' in model or '8865' in model:
        return 'sip8832.14-4-1-0001-36'
    elif '88' in model:
        return 'sip88xx.14-4-1-0001-36'
    elif '78' in model:
        return 'sip78xx.14-4-1-0001-36'

    return None


def update_phone_load(phone_identifier):
    """Update phone load based on phone model
    Args:
        phone_identifier (string): Phone identifier (MAC or SEP name)
    """
    formatted_identifier = format_phone_identifier(phone_identifier)
    logger.info(f'Updating phone load for: {formatted_identifier}')

    phone = axl.get_Phone(name=formatted_identifier)
    if not phone.get('success'):
        logger.error(f'Phone {formatted_identifier} not found')
        return

    phone_data = phone.get('response', {})
    phone_model = phone_data.get('model', '')
    logger.info(f'Phone model: {phone_model}')

    phone_load = get_phone_load_for_model(phone_model)
    if not phone_load:
        logger.warning(f'No Phone Load mapping for model: {phone_model}')
        return

    logger.info(f'Setting Phone Load: {phone_load}')

    update_data = {
        'loadInformation': phone_load
    }

    result = axl.update_Phone(name=formatted_identifier, **update_data)
    if result.get('success'):
        logger.info(f'Phone load updated: {result.get("response")}')

        apply_result = axl.reset_Phone(name=formatted_identifier)
        if apply_result.get('success'):
            logger.info(f'Phone reset to apply settings: {apply_result.get("response")}')
        else:
            logger.error(f'Phone reset failed: {apply_result.get("error")}')
    else:
        logger.error(f'Phone load update failed: {result.get("error")}')


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
            update_single_phone()
            break


def update_single_phone():
    """
    Update phone load for a single phone
    """
    phone_identifier = input('Phone identifier (MAC or SEP name): ')
    update_phone_load(phone_identifier)


def use_csv():
    """
    Bulk update phone load for phones from CSV
    """
    print('\nCSV Must have header row')
    print('Column should be either "phone" (with SEP prefix) or "mac" (12-digit MAC address)')
    input_file = input('Enter CSV file name or full path: ') or 'phone.csv'
    with open(input_file, 'r', encoding='utf8') as my_file:
        csv_file = DictReader(my_file)
        has_phone_col = 'phone' in (csv_file.fieldnames or [])
        has_mac_col = 'mac' in (csv_file.fieldnames or [])

        if not has_phone_col and not has_mac_col:
            logger.error('CSV must contain either "phone" or "mac" column')
            return

        for row in csv_file:
            phone_identifier = None
            if has_phone_col:
                phone_identifier = row['phone']
            elif has_mac_col:
                phone_identifier = row['mac']

            if not phone_identifier:
                logger.error('Phone identifier not found in row')
                continue

            update_phone_load(phone_identifier)


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = getpass.getpass('Enter CUCM Password for ' + username + ':')

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-update-phone-load-{cucm}.log"
    logger = setup_logger(log_file)
    logger.info("Update Phone Load - Started")

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username,password=password,wsdl=wsdl,cucm=cucm,cucm_version=version)

    # Calling the main function
    main()
