#!/usr/bin/env python3

"""
Update phone load on phones in CUCM based on phone model.

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
from setup.logger import setup_logger
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
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


def update_phone_load(axl, logger, phone_identifier):
    """Update phone load based on phone model
    Args:
        axl: AXL client instance
        logger: logger instance
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


def run_single_phone(axl, logger):
    """
    Update phone load for a single phone
    """
    phone_identifier = input('Phone identifier (MAC or SEP name): ')
    update_phone_load(axl, logger, phone_identifier)


def run_csv_file(axl, logger, csv_file_path):
    """
    Bulk update phone load for phones from CSV
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

            update_phone_load(axl, logger, phone_identifier)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run phone load update on a single cluster."""
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
    """Run phone load update on all clusters sequentially."""
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
    log_file = f"../_logs/{timestamp}-update-phone-load.log"
    logger = setup_logger(log_file)
    logger.info("Update Phone Load - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM')
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
            cluster = get_object_for_single_operation(basepath, 'CUCM')
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
        cluster = get_object_for_single_operation(basepath, 'CUCM')
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
