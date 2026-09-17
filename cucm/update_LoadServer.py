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
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
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


def update_load_server(axl, logger, phone_identifier):
    """Update phone Load Server using vendorConfig
    Args:
        axl: AXL client instance
        logger: logger instance
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


def run_single_phone(axl, logger):
    """
    Update Load Server for a single phone
    """
    phone_identifier = input('Phone identifier (MAC or SEP name): ')
    update_load_server(axl, logger, phone_identifier)


def run_csv_file(axl, logger, csv_file_path):
    """
    Bulk update Load Server for phones from CSV
    """
    print('\nCSV Must have header row')
    print('Column should be either "phone" (with SEP prefix) or "mac" (12-digit MAC address)')
    with open(csv_file_path, 'r', encoding='utf8') as my_file:
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

            update_load_server(axl, logger, phone_identifier)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run load server update on a single cluster."""
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        op_type = operation_params.get('type')
        if op_type == 'csv':
            run_csv_file(axl, logger, operation_params['csv_file'])
        else:  # single
            run_single_phone(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run load server update on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = input('Use same credentials for all clusters? (y/n) [default: y]: ').strip().lower()
    use_same = use_same in ('', 'y', 'yes')

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, operation_params, cluster_credentials, logger):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-update-load-server.log"
    logger = setup_logger(log_file)
    logger.info("Update Load Server - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        response = input(f'{len(clusters_data)} clusters found. Use multiple clusters?: (y/n) ') or 'n'
        if response.lower() in ('y', 'yes'):
            # Gather operation parameters for multi-cluster
            input_type_csv = input('Use CSV?: (y/n)') or 'n'
            if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
                print('\nCSV Must have header row')
                print('Column should be either "phone" (with SEP prefix) or "mac" (12-digit MAC address)')
                csv_file = input('Enter CSV file name or full path: ') or 'phone.csv'
                operation_params = {'type': 'csv', 'csv_file': csv_file}
            else:
                operation_params = {'type': 'single'}
            run_on_all_clusters(basepath, clusters_data, operation_params, logger)
        else:
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUCM', cluster['name'])
            server = cluster['server']
            version = cluster['version']

            wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
            wsdl = wsdl_dir.absolute().as_uri()
            axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

            input_type_csv = input('Use CSV?: (y/n)') or 'n'
            if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
                print('\nCSV Must have header row')
                print('Column should be either "phone" (with SEP prefix) or "mac" (12-digit MAC address)')
                csv_file = input('Enter CSV file name or full path: ') or 'phone.csv'
                run_csv_file(axl, logger, csv_file)
            else:
                run_single_phone(axl, logger)
    else:
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUCM', cluster['name'])
        server = cluster['server']
        version = cluster['version']

        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        input_type_csv = input('Use CSV?: (y/n)') or 'n'
        if str(input_type_csv) in ("Yes", "yes", "Y", "y"):
            print('\nCSV Must have header row')
            print('Column should be either "phone" (with SEP prefix) or "mac" (12-digit MAC address)')
            csv_file = input('Enter CSV file name or full path: ') or 'phone.csv'
            run_csv_file(axl, logger, csv_file)
        else:
            run_single_phone(axl, logger)
