#!/usr/bin/env python3

"""
Find Route Patterns with Dot Format but Missing Non-Dot Format

Connects to CUCM, retrieves all route patterns, and identifies patterns
that exist in dotted format (\+.12702106713) but NOT in standard format
(\+12702106713). Exports mismatches to a CSV file.

CSV Output Format:
dottedPattern, standardPattern, exists, description

"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from csv import DictWriter
import time
import urllib3
from general import serverSetup
from setup.logger import setup_logger
from ucmAPI import AXL

log_filename_prefix = 'Remedy-RP-'


def filter_patterns_by_description(route_patterns, description_filter):
    """
    Filter route patterns by description text.

    Args:
        route_patterns (list): List of route pattern dicts
        description_filter (str): Text to match in description (case-insensitive)

    Returns:
        list: Filtered route patterns
    """
    if not description_filter or description_filter.strip() == '':
        return route_patterns

    filter_lower = description_filter.lower()
    return [p for p in route_patterns if filter_lower in (p.get('description', '') or '').lower()]


def find_dot_pattern_mismatches(route_patterns):
    """
    Find route patterns in dotted format without matching standard format.

    Args:
        route_patterns (list): List of route pattern dicts

    Returns:
        list: List of dicts with dotted pattern info and standard pattern status
    """
    # Build a set of all pattern strings for quick lookup
    all_patterns = {p.get('pattern', '') for p in route_patterns}

    mismatches = []

    for pattern_obj in route_patterns:
        pattern = pattern_obj.get('pattern', '')

        # Check if pattern starts with \+. (dotted format)
        if pattern.startswith('\\+.'):
            # Remove the dot to get the standard format
            standard_pattern = pattern.replace('\\+.', '\\+', 1)

            # Check if standard format exists in patterns
            if standard_pattern not in all_patterns:
                mismatches.append({
                    'dottedPattern': pattern,
                    'standardPattern': standard_pattern,
                    'exists': 'No',
                    'description': pattern_obj.get('description', ''),
                })
            else:
                mismatches.append({
                    'dottedPattern': pattern,
                    'standardPattern': standard_pattern,
                    'exists': 'Yes',
                    'description': pattern_obj.get('description', ''),
                })

    return sorted(mismatches, key=lambda x: (x['exists'] == 'Yes', x['dottedPattern']))


def export_mismatches_to_csv(mismatches, total_route_count, filtered_route_count, description_filter):
    """
    Export mismatch results to a CSV file with timestamp

    Args:
        mismatches (list): List of mismatch dictionaries
        total_route_count (int): Total route patterns count
        filtered_route_count (int): Filtered route patterns count
        description_filter (str): Description filter text applied
    """
    timestamp = time.strftime("%Y_%m_%d-%H_%M_%S")
    output_filename = f'remedy_RP_dotted-{timestamp}.csv'

    missing_count = len([m for m in mismatches if m['exists'] == 'No'])
    has_count = len([m for m in mismatches if m['exists'] == 'Yes'])

    try:
        with open(output_filename, 'w', newline='', encoding='utf8') as csvfile:
            # Write summary as comments first
            csvfile.write(f'# Total Route Patterns: {total_route_count}\n')
            if description_filter:
                csvfile.write(f'# Description Filter: {description_filter}\n')
            csvfile.write(f'# Analyzed Patterns: {filtered_route_count}\n')
            csvfile.write(f'# Dotted Format Patterns Found: {len(mismatches)}\n')
            csvfile.write(f'# Missing Standard Format: {missing_count}\n')
            csvfile.write(f'# Has Standard Format: {has_count}\n\n')

            fieldnames = ['dottedPattern', 'standardPattern', 'exists', 'description']
            writer = DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for mismatch in mismatches:
                writer.writerow(mismatch)

            logger.info(f'Successfully exported {len(mismatches)} dotted format patterns to {output_filename}')
            print(f'\nDotted format pattern analysis exported to: {output_filename}')
            print(f'Total Route Patterns: {total_route_count}')
            if description_filter:
                print(f'Description Filter: {description_filter}')
            print(f'Analyzed Patterns: {filtered_route_count}')
            print(f'Dotted Format Patterns Found: {len(mismatches)}')
            print(f'Missing Standard Format: {missing_count}')
            print(f'Has Standard Format: {has_count}')

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
    logger = setup_logger(basepath / 'logs' / (log_filename_prefix + cucm + '-' + (time.strftime("%Y_%m_%d-%H_%M_%S")) + '.log'))

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

    # Prompt for description filter
    description_filter = input('Filter patterns by description (leave blank for all): ').strip()

    # Apply filter
    if description_filter:
        filtered_patterns = filter_patterns_by_description(route_patterns, description_filter)
        logger.info(f'Filtered to {len(filtered_patterns)} patterns matching description: {description_filter}')
        print(f'Filtered to {len(filtered_patterns)} patterns matching description')
    else:
        filtered_patterns = route_patterns
        logger.info('No description filter applied')

    # Find dotted format mismatches
    logger.info('Analyzing route patterns for dotted format mismatches')
    mismatches = find_dot_pattern_mismatches(filtered_patterns)

    # Export results
    if len(route_patterns) > 0:
        export_mismatches_to_csv(mismatches, len(route_patterns), len(filtered_patterns), description_filter)
    else:
        logger.warning('No route patterns to analyze')
        print('No route patterns to analyze')
