#!/usr/bin/env python3
# TITLE: Translation Patterns Remediate

"""
Find and Delete Translation Patterns
Searches for Translation Patterns by pattern, partition, or description, and optionally
deletes matching patterns from a CUCM cluster.

CSV Format (file name only, read from the _DATA folder; default: remediate_translation_patterns.csv, header row required):
  pattern
  [pattern_string]
  Example:
    pattern
    9XXX
    555...
    ABCD

Supports single pattern search or CSV file of patterns, on a single CUCM cluster.

Search Modes:
  - CSV: Provide a CSV file with pattern column
  - Manual: Search by Pattern, Partition, or Description with wildcards

Deletion Options:
  - n: Do not delete (cancel)
  - y: Delete all matching patterns
  - i: Confirm each pattern individually before deletion

Arguments:
  --debug   Enable debug-level console logging (default: info level)
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import argparse
import csv
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no, prompt_delete_mode
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL

CSV_COLUMNS = ('pattern',)


def read_patterns_from_csv(csv_path, logger):
    """Read translation pattern from the CSV file"""
    if not Path(csv_path).exists():
        logger.error('CSV file not found: %s', csv_path)
        print(f"Error: CSV file not found: {csv_path}")
        return []

    patterns = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fields = {(h or '').strip().lower(): h for h in (reader.fieldnames or [])}
        column = next((fields[c] for c in CSV_COLUMNS if c in fields), None)
        if not column:
            print(f"Error: CSV must have one of these columns: {', '.join(CSV_COLUMNS)}")
            logger.error('CSV missing pattern column')
            return []
        for row in reader:
            value = (row.get(column) or '').strip()
            if value:
                patterns.append(value)
    logger.info('Read %d patterns from %s', len(patterns), csv_path)
    return patterns


def search_translation_patterns(search_patterns, search_by, axl, logger):
    """Search for translation patterns. Returns (patterns found, patterns not found)"""
    found = []
    not_found = []
    seen = set()

    for search_value in search_patterns:
        result = axl.find_translation_patterns_sql(search_by, search_value)
        if not result.get('success'):
            logger.warning('Search failed for %s=%s: %s', search_by, search_value, result.get('error'))
            not_found.append(search_value)
            continue

        rows = result.get('response', [])
        if not rows:
            logger.warning('No patterns found for %s=%s', search_by, search_value)
            not_found.append(search_value)
            continue

        for row in rows:
            key = (row['pattern'], row['partition'])
            if key not in seen:
                seen.add(key)
                found.append(row)
                logger.info('Found translation pattern: %s (partition: %s, description: %s)',
                           row['pattern'], row['partition'] or '<None>', row['description'])

    return found, not_found


def fmt_pattern(pattern, partition, description=''):
    """Format pattern for display"""
    desc_str = f' - {description}' if description else ''
    return f"{pattern} (partition: {partition or '<None>'}){desc_str}"


def print_patterns_available(patterns, not_found):
    """List the patterns available for deletion and any search terms not found"""
    print(f"\n{'='*80}")
    print(f"Translation Patterns Available for Deletion ({len(patterns)} found)")
    print(f"{'='*80}\n")
    for pattern in patterns:
        print(f"  {fmt_pattern(pattern['pattern'], pattern['partition'], pattern['description'])}")
    if not_found:
        print(f"\nSearch terms with no matches ({len(not_found)}):")
        for term in not_found:
            print(f"  - {term}")
    print(f"\n{'='*80}")


def delete_patterns(patterns, axl, logger, individual=False):
    """Delete the translation patterns. Returns (deleted count, failed count)"""
    deleted = 0
    failed = 0
    print("\nDeleting translation patterns...\n")
    for pattern in patterns:
        pat = pattern['pattern']
        part = pattern['partition']
        if individual and not prompt_yes_no(f"Delete pattern '{fmt_pattern(pat, part)}'?", default=False):
            print(f"  - Skipped: {fmt_pattern(pat, part)}")
            logger.info('Skipped pattern: %s in %s', pat, part or '<None>')
            continue
        try:
            result = axl.remove_TransPattern(pat, part or None)
        except Exception as e:
            result = {'success': False, 'error': str(e)}
        if result.get('success'):
            print(f"  ✓ {fmt_pattern(pat, part)}")
            logger.info('Deleted pattern: %s in %s', pat, part or '<None>')
            deleted += 1
        else:
            print(f"  ✗ {fmt_pattern(pat, part)} - {result.get('error')}")
            logger.error('Failed to delete pattern %s in %s: %s', pat, part or '<None>', result.get('error'))
            failed += 1
    return deleted, failed


def print_summary(patterns_found, patterns_deleted, patterns_failed, logger):
    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print(f"Patterns found:      {patterns_found}")
    print(f"Patterns deleted:    {patterns_deleted}")
    print(f"Patterns failed:     {patterns_failed}")
    logger.info('Summary - patterns found: %d, deleted: %d, failed: %d',
                patterns_found, patterns_deleted, patterns_failed)
    print(f"{'='*80}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Find and delete translation patterns')
    parser.add_argument('--debug', action='store_true', help='Enable debug-level console logging')
    args = parser.parse_args()

    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-remediate-translation-patterns.log"
    logger = setup_logger(log_file, debug=args.debug)
    logger.info("Translation Patterns Remediate - Started")

    print("="*80)
    print("Translation Patterns Remediate")
    print("="*80)

    cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
    if not cluster:
        print("Error: Unable to load cluster information")
        sys.exit(1)

    username, password = load_credentials('CUCM', cluster['name'])

    server = cluster['server']
    version = cluster['version']
    wsdl = (script_dir / 'schema' / version / 'AXLAPI.wsdl').absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

    continue_searching = True

    while continue_searching:
        use_csv = prompt_yes_no('\nSearch using CSV file?', default=False)

        if use_csv:
            csv_name = input('Enter CSV file name in _DATA folder [remediate_translation_patterns.csv]: ').strip() or 'remediate_translation_patterns.csv'
            data_dir = script_dir.parent / '_DATA'
            csv_file = str(data_dir / Path(csv_name).name)
            logger.info("Using CSV file: %s", csv_file)
            search_patterns = read_patterns_from_csv(csv_file, logger)
            search_by = 'pattern'

            if not search_patterns:
                print("No search terms provided")
                if not prompt_yes_no('\nSearch again?', default=False):
                    logger.info("Translation Patterns Remediate - Completed")
                    sys.exit(0)
                continue

            print(f"\nSearching by {search_by} on {cluster['name']}...\n")
            patterns, not_found = search_translation_patterns(search_patterns, search_by, axl, logger)
            print_patterns_available(patterns, not_found)

            if not patterns:
                print("\nNo matching patterns found")
                if not prompt_yes_no('\nSearch again?', default=False):
                    logger.info("Translation Patterns Remediate - Completed")
                    sys.exit(0)
                continue
        else:
            patterns = []
            while not patterns:
                print("\nSearch by:")
                print("  1. Pattern (wildcard supported)")
                print("  2. Partition")
                print("  3. Description")
                choice = input("Select search method [1-3] [1]: ").strip() or '1'
                try:
                    choice_num = int(choice)
                    if choice_num == 1:
                        search_by = 'pattern'
                    elif choice_num == 2:
                        search_by = 'partition'
                    elif choice_num == 3:
                        search_by = 'description'
                    else:
                        print("Invalid selection")
                        continue
                except ValueError:
                    print("Invalid selection")
                    continue

                search_value = input(f'Enter {search_by} to search for (wildcard % supported): ').strip()
                if not search_value:
                    print("No search term provided")
                    continue

                search_patterns = [search_value]
                print(f"\nSearching by {search_by} on {cluster['name']}...\n")
                patterns, not_found = search_translation_patterns(search_patterns, search_by, axl, logger)
                print_patterns_available(patterns, not_found)

                if not patterns:
                    print("\nNo matching patterns found. Try another search.")
                    continue

        mode = prompt_delete_mode(f'\nDelete {len(patterns)} translation pattern(s)?')
        if mode == 'n':
            print("Deletion cancelled by user")
            logger.info("Deletion cancelled by user")
        else:
            deleted, failed = delete_patterns(patterns, axl, logger, individual=(mode == 'i'))
            print_summary(len(patterns), deleted, failed, logger)

        # Ask if user wants to search again
        if not prompt_yes_no('\nSearch again?', default=False):
            continue_searching = False

    logger.info("Translation Patterns Remediate - Completed")
