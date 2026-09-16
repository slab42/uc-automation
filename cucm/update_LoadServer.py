#!/usr/bin/env python3

"""
Update phone Load Server in CUCM to cloudupgrader.webex.com

Sets the load server directly on each phone using vendorConfig.

CUCM Cluster: select from clusters.csv or provide manually
Credentials: checks stored credentials in credentials.env

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
from lxml import etree
from setup.logger import setup_logger
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL


loadServerAddress = 'cloudupgrader.webex.com'


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


def update_load_server(phone_identifier):
    """Update phone Load Server using vendorConfig
    Args:
        phone_identifier (string): Phone identifier (MAC or SEP name)
    """
    formatted_identifier = format_phone_identifier(phone_identifier)
    logger.info(f'Updating Load Server for phone: {formatted_identifier}')

    phone = axl.get_Phone(name=formatted_identifier)
    if not phone.get('success'):
        logger.error(f'Phone {formatted_identifier} not found')
        return

    logger.info(f'Setting Load Server to: {loadServerAddress}')

    vendor_config_elem = etree.Element('vendorConfig')
    load_server_elem = etree.SubElement(vendor_config_elem, 'loadServer')
    load_server_elem.text = loadServerAddress

    update_data = {
        'vendorConfig': vendor_config_elem
    }

    result = axl.update_Phone(name=formatted_identifier, **update_data)
    if result.get('success'):
        logger.info(f'Phone Load Server updated: {result.get("response")}')

        apply_result = axl.reset_Phone(name=formatted_identifier)
        if apply_result.get('success'):
            logger.info(f'Phone reset to apply settings: {apply_result.get("response")}')
        else:
            logger.error(f'Phone reset failed: {apply_result.get("error")}')
    else:
        logger.error(f'Phone Load Server update failed: {result.get("error")}')


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
    Update Load Server for a single phone
    """
    phone_identifier = input('Phone identifier (MAC or SEP name): ')
    update_load_server(phone_identifier)


def use_csv():
    """
    Bulk update Load Server for phones from CSV
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

            update_load_server(phone_identifier)


if __name__ == '__main__':
    basepath = Path.cwd()

    # Load cluster information from clusters.csv or interactive input
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
    log_file = f"../_logs/{timestamp}-update-load-server-{cucm}.log"
    logger = setup_logger(log_file)
    logger.info("Update Load Server - Started")

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username,password=password,wsdl=wsdl,cucm=cucm,cucm_version=version)

    # Calling the main function
    main()
