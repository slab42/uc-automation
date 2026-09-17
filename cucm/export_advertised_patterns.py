#!/usr/bin/env python3

"""
Export Advertised Patterns from CUCM to a CSV file

Connects to CUCM, retrieves all advertised patterns, and exports them
to a CSV file with date and time in the filename.

CUCM Cluster: select from clusters.csv or provide manually
Credentials: checks stored credentials in credentials.env

CSV Output Format:
description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictWriter
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



def export_patterns_to_csv_impl(patterns, server, logger):
    """
    Export advertised patterns to a CSV file with timestamp

    Args:
        patterns (list): List of advertised pattern dictionaries
        server (str): Server name to include in filename
        logger: logger instance
    """
    timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
    if server:
        output_filename = f'advertised_patterns-{server}-{timestamp}.csv'
    else:
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


def run_export(axl, logger, server):
    """Run pattern export on a single cluster."""
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
        export_patterns_to_csv_impl(patterns, server, logger)
        return True
    else:
        logger.error(f'Failed to retrieve advertised patterns: {result.get("error")}')
        print(f'Error: {result.get("error")}')
        return False


def run_operation_on_cluster(basepath, cluster_data, cluster_credentials, logger):
    """Run pattern export on a single cluster."""
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

        success = run_export(axl, logger, server)

        logger.info('Completed cluster: %s', cluster_name)
        if success:
            print(f"✓ Completed {cluster_name} ({server})")
        return success
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        logger.error(f"Exception on cluster {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, logger):
    """Run pattern export on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, cluster_credentials, logger):
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
    log_file = f"../_logs/{timestamp}-export-advertised-patterns.log"
    logger = setup_logger(log_file)
    logger.info("Export Advertised Patterns - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            run_on_all_clusters(basepath, clusters_data, logger)
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

            run_export(axl, logger, server)
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

        run_export(axl, logger, server)
