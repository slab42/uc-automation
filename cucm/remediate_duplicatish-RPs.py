#!/usr/bin/env python3

"""
Remediate Duplicate-ish Route Patterns in CUCM

Identifies route patterns that start with '.+' and have a corresponding pattern
starting with '+' with the same 11-digit suffix, then prompts to delete the
'.+' pattern (keeping the '+' pattern as the canonical version).

For example:
  .+1234567890 (dot-plus prefix)
  +1234567890  (plus prefix)

If both exist with the same 11-digit suffix, prompts to delete the '.+' version.
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import time
import urllib3
from general import serverSetup
from setup.logger import setup_logger
from ucmAPI import AXL



def extract_last_eleven_digits(pattern):
    """Extract the last 11 characters from a pattern string."""
    return pattern[-11:] if pattern else ''


def find_duplicate_patterns(route_patterns):
    """
    Find route patterns where '.+<digits>' and '+<digits>' coexist with same 11-digit suffix.

    Args:
        route_patterns (list): List of route pattern dicts

    Returns:
        list: List of dicts with duplicatish pattern pairs (dot_plus_pattern, plus_pattern, last_11_digits)
    """
    dot_plus_patterns = {}
    plus_patterns = {}

    for pattern_obj in route_patterns:
        pattern = pattern_obj.get('pattern', '')

        if pattern.startswith(r'\+.'):
            last_11 = extract_last_eleven_digits(pattern)
            dot_plus_patterns[last_11] = {
                'pattern': pattern,
                'routePartitionName': pattern_obj.get('routePartitionName', ''),
                'description': pattern_obj.get('description', ''),
            }
        elif pattern.startswith(r'\+'):
            last_11 = extract_last_eleven_digits(pattern)
            plus_patterns[last_11] = {
                'pattern': pattern,
                'routePartitionName': pattern_obj.get('routePartitionName', ''),
                'description': pattern_obj.get('description', ''),
            }

    duplicates = []
    for last_11, dot_plus_info in dot_plus_patterns.items():
        if last_11 in plus_patterns:
            duplicates.append({
                'dot_plus_pattern': dot_plus_info['pattern'],
                'dot_plus_partition': dot_plus_info['routePartitionName'],
                'dot_plus_description': dot_plus_info['description'],
                'plus_pattern': plus_patterns[last_11]['pattern'],
                'plus_partition': plus_patterns[last_11]['routePartitionName'],
                'plus_description': plus_patterns[last_11]['description'],
                'last_11_digits': last_11,
            })

    return sorted(duplicates, key=lambda x: x['last_11_digits'])


def prompt_delete_patterns(duplicates, axl):
    """
    Prompt user for each duplicate pair and delete '.+' patterns as confirmed.

    Args:
        duplicates (list): List of duplicate dictionaries
        axl: AXL client instance
    """
    deleted_count = 0
    skipped_count = 0

    for dup in duplicates:
        dot_plus = dup['dot_plus_pattern']
        plus = dup['plus_pattern']
        dot_plus_desc = dup['dot_plus_description'] or '(no description)'
        plus_desc = dup['plus_description'] or '(no description)'

        print(f'\nDuplicate-ish patterns found:')
        print(f'  To DELETE (dot-plus):  {dot_plus}')
        print(f'    Description: {dot_plus_desc}')
        print(f'  To KEEP (plus):        {plus}')
        print(f'    Description: {plus_desc}')

        response = input(f'Delete {dot_plus}? (y/n): ').strip().lower()

        if response == 'y':
            result = axl.remove_Route_Pattern(
                pattern=dup['dot_plus_pattern'],
                routePartitionName=dup['dot_plus_partition']
            )
            if result.get('success'):
                logger.info(f'Deleted route pattern: {dot_plus}')
                print(f'Deleted: {dot_plus}')
                deleted_count += 1
            else:
                logger.error(f'Failed to delete {dot_plus}: {result.get("error")}')
                print(f'Error deleting {dot_plus}: {result.get("error")}')
        else:
            logger.info(f'Skipped deletion of: {dot_plus}')
            print(f'Skipped: {dot_plus}')
            skipped_count += 1

    print(f'\nSummary:')
    print(f'  Deleted: {deleted_count}')
    print(f'  Skipped: {skipped_count}')
    logger.info(f'Remediation complete. Deleted: {deleted_count}, Skipped: {skipped_count}')


if __name__ == '__main__':
    # Set current working directory to basepath
    basepath = Path.cwd()

    # Get server and login credentials
    cucmInfoFile = input('CUCM JSON File (cucm-info.json): ') or 'cucm-info.json'
    username, password, cucm, version = serverSetup(basepath / cucmInfoFile, 'username', 'password', 'server', 'version', 'non-api')
    if password == '':
        password = input('Enter CUCM Password for ' + username + ':')

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remediate-duplicatish-rps-{cucm}.log"
    logger = setup_logger(log_file)
    logger.info("Remediate Duplicatish Rps - Started")

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=cucm, cucm_version=version)

    # Get all route patterns
    logger.info('Fetching route patterns from CUCM')
    route_result = axl.list_route_patterns()

    if not route_result.get('success'):
        logger.error(f'Failed to retrieve route patterns: {route_result.get("error")}')
        print(f'Error: {route_result.get("error")}')
        exit(1)

    route_response = route_result.get('response', [])
    if not route_response or route_response == '':
        route_patterns = []
    elif isinstance(route_response, list):
        route_patterns = route_response
    else:
        route_patterns = [route_response]

    logger.info(f'Retrieved {len(route_patterns)} route patterns')

    # Find duplicate-ish patterns
    logger.info('Searching for duplicate-ish patterns (.+ vs +)')
    duplicates = find_duplicate_patterns(route_patterns)

    if duplicates:
        print(f'\nFound {len(duplicates)} duplicate-ish pattern pairs')
        logger.info(f'Found {len(duplicates)} duplicate-ish pattern pairs')
        prompt_delete_patterns(duplicates, axl)
    else:
        logger.info('No duplicate-ish patterns found')
        print('No duplicate-ish patterns found')
