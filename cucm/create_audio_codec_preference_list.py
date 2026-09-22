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
from datetime import datetime
import time
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


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
    csv_file = input('Enter CSV file name or full path [_DATA/audioCodecPreferenceLists.csv]: ') or '../_DATA/audioCodecPreferenceLists.csv'
    process_csv_file(axl, logger, csv_file)


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run the codec preference operation on a single cluster"""
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

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
        logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, operation_params, logger):
    """Run operation on all clusters sequentially"""
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    # Load credentials using the new loader
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

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-create-audio-codec-preference-list.log"
    logger = setup_logger(log_file)
    logger.info("Create Audio Codec Preference List - Started")

    use_multiple = False

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            if not clusters_data:
                print("No clusters found in clusters.csv")
                exit(1)

            use_csv = prompt_yes_no('Use CSV for Codec List?', default=False)

            if use_csv:
                csv_file = input('Enter CSV file name or full path [_DATA/audioCodecPreferenceLists.csv]: ') or str(basepath.parent / '_DATA' / 'audioCodecPreferenceLists.csv')
                operation_params = {'type': 'csv', 'csv_file': csv_file}
            else:
                name = input('Codec Preference List Name: ')
                description = input('Description (optional): ') or ''
                codec_input = input('Enter codecs (comma-separated, in priority order): ')
                codec_list = [codec.strip() for codec in codec_input.split(',')]
                operation_params = {'type': 'single', 'name': name, 'description': description, 'codec_list': codec_list}

            run_on_all_clusters(basepath, clusters_data, operation_params, logger)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
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

            use_csv = prompt_yes_no('Use CSV for Codec List?', default=False)
            if use_csv:
                interactive_csv_mode(axl, logger)
            else:
                interactive_single_mode(axl, logger)

    else:
        # No clusters found in CSV - single cluster mode with manual input
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

        use_csv = prompt_yes_no('Use CSV for Codec List?', default=False)
        if use_csv:
            interactive_csv_mode(axl, logger)
        else:
            interactive_single_mode(axl, logger)
