#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Create a Region with Audio Codec Preference List and Max Audio Bit Rate
Then update all Device Pools to use the new Region

Supports single or multiple CUCM clusters

Single mode: Prompts for region name, codec preference list, and max audio bit rate

CSV Format:
region_name, audio_codec_preference_list, max_audio_bit_rate
Region-G711, Standard-G711, 256
Region-Premium, Premium-Codecs, 512
Region-G729, G729-Preferred, 64

max_audio_bit_rate values: 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640, 704, 768 (in kbps)

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
    """Process regions and device pool updates from CSV file"""
    with open(csv_file, 'r', encoding='utf8') as my_file:
        csv_reader = reader(my_file)
        next(my_file)
        for row in csv_reader:
            if not row or not row[0].strip():
                continue
            region_name = row[0].strip()
            codec_pref_list = row[1].strip() if len(row) > 1 else ''
            max_audio_bit_rate = row[2].strip() if len(row) > 2 else ''

            if not region_name:
                logger.warning('Skipping row: no region name provided')
                continue

            process_region(axl, logger, region_name, codec_pref_list, max_audio_bit_rate)


def process_region(axl, logger, region_name, codec_pref_list, max_audio_bit_rate):
    """Create region and update all device pools"""
    logger.info('=' * 60)
    logger.info('Creating Region: %s', region_name)

    result = axl.add_Region(region=region_name, codec_preference_list=codec_pref_list, max_audio_bit_rate=max_audio_bit_rate)
    if not result.get('success'):
        logger.error('Failed to create region %s: %s', region_name, result.get('error'))
        return False

    logger.info(result.get('response'))

    logger.info('Retrieving all device pools...')
    pools_result = axl.list_DevicePools()
    if not pools_result.get('success'):
        logger.error('Failed to retrieve device pools: %s', pools_result.get('error'))
        return False

    device_pools = pools_result.get('response')
    if not device_pools:
        logger.warning('No device pools found')
        return True

    if not isinstance(device_pools, list):
        device_pools = [device_pools]

    logger.info('Found %d device pools. Updating all to use region %s...', len(device_pools), region_name)

    updated_count = 0
    failed_count = 0

    for pool in device_pools:
        pool_name = pool.get('name')
        if not pool_name:
            continue

        logger.info('Updating device pool: %s', pool_name)
        update_result = axl.update_Device_Pool(name=pool_name, region_name=region_name)
        if update_result.get('success'):
            logger.info(update_result.get('response'))
            updated_count += 1
        else:
            logger.error('Failed to update device pool %s: %s', pool_name, update_result.get('error'))
            failed_count += 1

    logger.info('=' * 60)
    logger.info('Region %s completed: %d updated, %d failed', region_name, updated_count, failed_count)
    logger.info('=' * 60)
    return True


def run_operation_on_cluster(basepath, cluster_data, operation_params, cluster_credentials, logger):
    """Run the region creation operation on a single cluster"""
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
            process_region(axl, logger, operation_params['region_name'], operation_params['codec_pref_list'], operation_params['max_audio_bit_rate'])

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
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
    log_file = f"../_logs/{timestamp}-create-region-update-device-pools.log"
    logger = setup_logger(log_file)
    logger.info("Create Region Update Device Pools - Started")

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)
        if use_multiple:
            use_csv = prompt_yes_no('Use CSV?', default=False)

            if use_csv:
                csv_file = input('Enter CSV file name or full path [_DATA/createRegions.csv]: ') or str(basepath.parent / '_DATA' / 'createRegions.csv')
                operation_params = {'type': 'csv', 'csv_file': csv_file}
            else:
                region_name = input('Region Name: ')
                codec_pref_list = input('Audio Codec Preference List Name (optional): ') or ''
                max_audio_bit_rate = input('Maximum Audio Bit Rate in kbps (optional): ') or ''
                operation_params = {
                    'type': 'single',
                    'region_name': region_name,
                    'codec_pref_list': codec_pref_list,
                    'max_audio_bit_rate': max_audio_bit_rate
                }

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
                csv_file = input('Enter CSV file name or full path [_DATA/createRegions.csv]: ') or str(basepath.parent / '_DATA' / 'createRegions.csv')
                process_csv_file(axl, logger, csv_file)
            else:
                region_name = input('Region Name: ')
                codec_pref_list = input('Audio Codec Preference List Name (optional): ') or ''
                max_audio_bit_rate = input('Maximum Audio Bit Rate in kbps (optional): ') or ''
                process_region(axl, logger, region_name, codec_pref_list, max_audio_bit_rate)

    else:
        # Single cluster mode
        # Load cluster information from clusters.csv or interactive input
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
            csv_file = input('Enter CSV file name or full path [_DATA/createRegions.csv]: ') or str(basepath.parent / '_DATA' / 'createRegions.csv')
            process_csv_file(axl, logger, csv_file)
        else:
            region_name = input('Region Name: ')
            codec_pref_list = input('Audio Codec Preference List Name (optional): ') or ''
            max_audio_bit_rate = input('Maximum Audio Bit Rate in kbps (optional): ') or ''
            process_region(axl, logger, region_name, codec_pref_list, max_audio_bit_rate)
