#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Create Audio Codec Preference List individually or from a list in CSV
Supports single or multiple CUCM clusters

Single mode: Prompts for preference list name, description, and codec list (comma-separated)

CSV Format:
name, description, codec1, codec2, codec3, codec4, ...
Standard-G711, Standard configuration, G.711-ulaw, G.729, G.723
Premium-Codecs, Premium audio quality, G.711-ulaw, G.722, G.711-alaw, G.729

Codec order matters - first codec has highest priority.
Common codecs: G.711-ulaw, G.711-alaw, G.729, G.723, G.722, G.722.1, iLBC, Opus

For multiple clusters, create a clusters.csv file with cluster configurations.
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import reader
import time
import getpass
import urllib3
from setup.logger import setup_logger
from ucmAPI import AXL

log_filename_prefix = 'Create-Audio-Codec-Preference-List-'

def process_csv_file(axl, logger, csv_file):
    """Process codecs from CSV file"""
    with open(csv_file, 'r', encoding='utf8') as my_file:
        csv_reader = reader(my_file)
        next(my_file)
        for row in csv_reader:
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            description = row[1].strip() if len(row) > 1 else ''
            codec_list = [codec.strip() for codec in row[2:] if codec.strip()] if len(row) > 2 else []

            if not codec_list:
                logger.warning('Skipping %s: no codecs provided', name)
                continue

            logger.info('Creating Codec Preference List: %s with codecs: %s', name, ', '.join(codec_list))
            result = axl.add_audio_codec_preference_list(name=name, codec_list=codec_list, description=description)
            if result.get('success'):
                logger.info(result.get('response'))
            else:
                logger.error(result.get('error'))


def run_single_codec(axl, logger, name, description, codec_list):
    """Create a single codec preference list"""
    logger.info('Creating Codec Preference List: %s with codecs: %s', name, ', '.join(codec_list))
    result = axl.add_audio_codec_preference_list(name=name, codec_list=codec_list, description=description)
    if result.get('success'):
        logger.info(result.get('response'))
    else:
        logger.error(result.get('error'))


def interactive_single_mode(axl, logger):
    """Interactive mode for single codec preference list"""
    name = input('Codec Preference List Name: ')
    description = input('Description (optional): ') or ''
    codec_input = input('Enter codecs (comma-separated, in priority order): ')
    codec_list = [codec.strip() for codec in codec_input.split(',')]
    run_single_codec(axl, logger, name, description, codec_list)


def interactive_csv_mode(axl, logger):
    """Interactive mode for CSV input"""
    print('\nCSV must have header row: name, description, codec1, codec2, codec3, ...')
    print('Field Format: name, description, codec1, codec2, codec3, ...')
    print('Description can be empty. Codec order matters - first codec has highest priority')
    csv_file = input('Enter CSV file name or full path: ') or 'audioCodecPreferenceLists.csv'
    process_csv_file(axl, logger, csv_file)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials):
    """Run the codec preference operation on a single cluster"""
    try:
        cluster_name = cluster_data['cluster_name']
        server = cluster_data['server']
        version = cluster_data['version']

        username = cluster_credentials[cluster_name]['username']
        password = cluster_credentials[cluster_name]['password']

        # Setup Logging
        logger = setup_logger(basepath / 'logs' / (log_filename_prefix + server + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log'))

        # Setup AXL Connection to CUCM
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        op_type = operation_params['type']
        if op_type == 'csv':
            process_csv_file(axl, logger, operation_params['csv_file'])
        elif op_type == 'single':
            run_single_codec(axl, logger, operation_params['name'], operation_params['description'], operation_params['codec_list'])

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    # Get credentials
    print("Credential Configuration:")
    use_same_creds = input('Use the same username/password for all clusters?: (y/n) ') or 'y'

    cluster_credentials = {}

    if use_same_creds.lower() in ('y', 'yes'):
        username = input('Username: ')
        password = getpass.getpass('Password: ')
        for cluster in clusters_data:
            cluster_credentials[cluster['cluster_name']] = {'username': username, 'password': password}
    else:
        for cluster in clusters_data:
            print(f"\nCluster: {cluster['cluster_name']} ({cluster['server']})")
            username = input(f'  Username: ')
            password = getpass.getpass(f'  Password: ')
            cluster_credentials[cluster['cluster_name']] = {'username': username, 'password': password}

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, operation_params, cluster_credentials):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


def read_clusters_csv(csv_file):
    """Read clusters from CSV file"""
    clusters = []
    with open(csv_file, 'r', encoding='utf8') as my_file:
        csv_reader = reader(my_file)
        header = next(my_file)
        for row in csv_reader:
            if not row or not row[0].strip():
                continue
            cluster_name = row[0].strip()
            server = row[1].strip() if len(row) > 1 else ''
            version = row[2].strip() if len(row) > 2 else ''

            if not cluster_name or not server or not version:
                print(f"Skipping incomplete cluster row: {row}")
                continue

            clusters.append({
                'cluster_name': cluster_name,
                'server': server,
                'version': version
            })
    return clusters


if __name__ == '__main__':
    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    clusters_file = basepath / 'clusters.csv'
    use_multiple = False

    if clusters_file.exists():
        response = input('clusters.csv found. Use multiple clusters?: (y/n) ') or 'n'
        if response.lower() in ('y', 'yes'):
            use_multiple = True

    if use_multiple:
        clusters_data = read_clusters_csv(clusters_file)

        if not clusters_data:
            print("No clusters found in clusters.csv")
            exit(1)

        csv_mode_response = input('Use CSV for Codec List?: (y/n) ') or 'n'

        if csv_mode_response.lower() in ('y', 'yes'):
            csv_file = input('Enter CSV file name or full path: ') or 'audioCodecPreferenceLists.csv'
            operation_params = {'type': 'csv', 'csv_file': csv_file}
        else:
            name = input('Codec Preference List Name: ')
            description = input('Description (optional): ') or ''
            codec_input = input('Enter codecs (comma-separated, in priority order): ')
            codec_list = [codec.strip() for codec in codec_input.split(',')]
            operation_params = {'type': 'single', 'name': name, 'description': description, 'codec_list': codec_list}

        run_on_all_clusters(basepath, clusters_data, operation_params)

    else:
        # Single cluster mode
        server = input('CUCM Server IP: ')
        version = input('CUCM Version (e.g., 15.0): ')

        username = input('Username: ')
        password = getpass.getpass('Password: ')

        logger = setup_logger(basepath / 'logs' / (log_filename_prefix + server + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log'))

        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        input_type_csv = input('Use CSV for Codec List?: (y/n) ') or 'n'
        if input_type_csv.lower() in ('y', 'yes'):
            interactive_csv_mode(axl, logger)
        else:
            interactive_single_mode(axl, logger)
