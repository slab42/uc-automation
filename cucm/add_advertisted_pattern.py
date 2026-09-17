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
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader
from datetime import datetime
import time
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)
from ucmAPI import AXL

def add_single_pattern(axl, logger, description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend):
    """Add a single Advertised Pattern"""
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
    return result


def run_single_pattern(axl, logger):
    """Prompt for and add a single Advertised Pattern"""
    description = input('Description: ')
    pattern = input('Pattern: ')
    patternType = input('Pattern Type: ')
    hostedRoutePSTNRule = input('Route PSTN Rule: (or hit enter for - No PSTN)') or 'No PSTN'
    pstnFailStrip = input('PSTN Digit Strip: (or hit enter for None)') or ''
    if pstnFailStrip == '':
        pstnFailStrip = '0'
    pstnFailPrepend = input('PSTN Prepend: (or hit enter for None)') or ''
    add_single_pattern(axl, logger, description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend)


def run_csv_file(axl, logger, csv_file_path):
    """Bulk Import Patterns from CSV"""
    with open(csv_file_path, 'r', encoding='utf8') as my_file:
        csv_file = reader(my_file)
        next(my_file)
        for row in csv_file:
            description = row[0]
            pattern = row[1]
            patternType = row[2]
            hostedRoutePSTNRule = row[3]
            pstnFailStrip = row[4]
            pstnFailPrepend = row[5]
            add_single_pattern(axl, logger, description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run pattern operations on a single cluster."""
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
            run_single_pattern(axl, logger)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run pattern operations on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

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
    log_file = f"../_logs/{timestamp}-add-advertised-pattern.log"
    logger = setup_logger(log_file)
    logger.info("Add Advertised Pattern - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            # Gather operation parameters for multi-cluster
            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV Must have header row and must contain only 1 pattern settings per row')
                print('Field Order: description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend')
                csv_file = input('Enter CSV file name or full path: ') or 'advertisedPatterns.csv'
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

            use_csv = prompt_yes_no('Use CSV?', default=False)
            if use_csv:
                print('\nCSV Must have header row and must contain only 1 pattern settings per row')
                print('Field Order: description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend')
                csv_file = input('Enter CSV file name or full path: ') or 'advertisedPatterns.csv'
                run_csv_file(axl, logger, csv_file)
            else:
                run_single_pattern(axl, logger)
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

        use_csv = prompt_yes_no('Use CSV?', default=False)
        if use_csv:
            print('\nCSV Must have header row and must contain only 1 pattern settings per row')
            print('Field Order: description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend')
            csv_file = input('Enter CSV file name or full path: ') or 'advertisedPatterns.csv'
            run_csv_file(axl, logger, csv_file)
        else:
            run_single_pattern(axl, logger)
