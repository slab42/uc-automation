#!/usr/bin/env python3

"""
Compare Advertised Patterns with Route Patterns in CUCM

Connects to CUCM, retrieves all advertised patterns and route patterns,
compares the last 10 digits of each, and exports patterns that exist in
one set but not the other to a CSV file.

CSV Output Format:
pattern, patternType, source, lastTenDigits
- source: 'Advertised Only' or 'Route Only'
- lastTenDigits: Last 10 digits of the pattern (or full pattern if < 10 digits)

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictWriter
from datetime import datetime
import time
import urllib3
from general import serverSetup
from setup.logger import setup_logger
from ucmAPI import AXL



def extract_last_ten_digits(pattern):
    """
    Extract the last 10 digits from a pattern string.
    Handles patterns with special characters like X, ., #, etc.

    Args:
        pattern (str): The pattern string

    Returns:
        str: Last 10 characters of the pattern (or full pattern if < 10 chars)
    """
    return pattern[-10:] if pattern else ''


def compare_patterns(advertised_patterns, route_patterns):
    """
    Compare advertised patterns and route patterns, returning mismatches.

    Args:
        advertised_patterns (list): List of advertised pattern dicts
        route_patterns (list): List of route pattern dicts

    Returns:
        list: List of dicts with pattern info and source of mismatch
    """
    # Extract last 10 digits from each pattern set
    adv_last_ten = {}
    for pattern_obj in advertised_patterns:
        pattern = pattern_obj.get('pattern', '')
        last_ten = extract_last_ten_digits(pattern)
        adv_last_ten[last_ten] = {
            'pattern': pattern,
            'patternType': pattern_obj.get('patternType', ''),
        }

    route_last_ten = set()
    for pattern_obj in route_patterns:
        pattern = pattern_obj.get('pattern', '')
        last_ten = extract_last_ten_digits(pattern)
        route_last_ten.add(last_ten)

    # Find patterns that exist in one set but not the other
    mismatches = []

    # Advertised patterns not in route patterns
    for last_ten, adv_info in adv_last_ten.items():
        if last_ten not in route_last_ten:
            mismatches.append({
                'pattern': adv_info['pattern'],
                'patternType': adv_info['patternType'],
                'source': 'Advertised Only',
                'lastTenDigits': last_ten,
            })

    # Route patterns not in advertised patterns (need to re-fetch for route info)
    route_pattern_objs = {extract_last_ten_digits(p.get('pattern', '')): p
                          for p in route_patterns}

    for last_ten in route_last_ten:
        if last_ten not in adv_last_ten:
            route_info = route_pattern_objs.get(last_ten, {})
            mismatches.append({
                'pattern': route_info.get('pattern', ''),
                'patternType': 'Route Only',
                'source': 'Route Only',
                'lastTenDigits': last_ten,
            })

    return sorted(mismatches, key=lambda x: (x['source'] != 'Advertised Only', x['lastTenDigits']))


def export_comparison_to_csv(mismatches, adv_count, route_count):
    """
    Export comparison results to a CSV file with timestamp

    Args:
        mismatches (list): List of mismatch dictionaries
        adv_count (int): Total advertised patterns count
        route_count (int): Total route patterns count
    """
    timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
    output_filename = f'pattern_comparison-{timestamp}.csv'

    adv_only_count = len([m for m in mismatches if m["source"] == "Advertised Only"])
    route_only_count = len([m for m in mismatches if m["source"] == "Route Only"])

    try:
        with open(output_filename, 'w', newline='', encoding='utf8') as csvfile:
            # Write summary as comments first
            csvfile.write(f'# Total Advertised Patterns: {adv_count}\n')
            csvfile.write(f'# Total Route Patterns: {route_count}\n')
            csvfile.write(f'# Mismatched Patterns: {len(mismatches)}\n')
            csvfile.write(f'# Advertised Only: {adv_only_count}\n')
            csvfile.write(f'# Route Only: {route_only_count}\n\n')

            fieldnames = ['pattern', 'patternType', 'source', 'lastTenDigits']
            writer = DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for mismatch in mismatches:
                writer.writerow(mismatch)

            logger.info(f'Successfully exported {len(mismatches)} mismatched patterns to {output_filename}')
            print(f'\nPattern comparison exported to: {output_filename}')
            print(f'Total Advertised Patterns: {adv_count}')
            print(f'Total Route Patterns: {route_count}')
            print(f'Mismatched Patterns: {len(mismatches)}')
            print(f'  - Advertised Only: {adv_only_count}')
            print(f'  - Route Only: {route_only_count}')

    except IOError as e:
        logger.error(f'Error writing to CSV file: {e}')
        print(f'Error writing CSV file: {e}')


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
    log_file = f"../_logs/{timestamp}-compare-advp-rp-{cucm}.log"
    logger = setup_logger(log_file)
    logger.info("Compare Advp Rp - Started")

    # Setup AXL Connection to CUCM
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    wsdlPath = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdlPath.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=cucm, cucm_version=version)

    # Get all advertised patterns
    logger.info('Fetching advertised patterns from CUCM')
    adv_result = axl.list_advertised_patterns()

    if not adv_result.get('success'):
        logger.error(f'Failed to retrieve advertised patterns: {adv_result.get("error")}')
        print(f'Error: {adv_result.get("error")}')
        exit(1)

    adv_response = adv_result.get('response', [])
    if not adv_response or adv_response == '':
        advertised_patterns = []
    elif isinstance(adv_response, list):
        advertised_patterns = adv_response
    else:
        advertised_patterns = [adv_response]

    logger.info(f'Retrieved {len(advertised_patterns)} advertised patterns')

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

    # Compare patterns
    logger.info('Comparing advertised patterns with route patterns')
    mismatches = compare_patterns(advertised_patterns, route_patterns)

    # Export results
    if mismatches or len(advertised_patterns) > 0 or len(route_patterns) > 0:
        export_comparison_to_csv(mismatches, len(advertised_patterns), len(route_patterns))
    else:
        logger.warning('No patterns to compare')
        print('No patterns to compare')
