#!/usr/bin/env python3
# TITLE: Locations Add

"""
Add Locations to RedSky (E911), individually or from a list in CSV.
A location lives under a Building; the Building is matched by name.

Usage:
    python3 locations_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add locations from a CSV file,
        or 'n' (default) to add a single location.

    If 'n' (single location):
        Select Building: numbered list of the Buildings in RedSky
            (0 places the location directly under the organization, for
            tenants without a Buildings layer)
        Location Name: name shown in RedSky
        Full Address: optional; leave blank to use the Building's address
        Info, Alternate ID, Callback Number, HTML Link URL, HTML Link Name,
            Org Name Override: all optional

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/locations_add.csv)

If a Building name in the CSV is not found in RedSky, the row is skipped and
logged. If RedSky reports an address as ambiguous or invalid, the location is
not created and the row is logged as an error.

CSV format (name, building, fullAddress, info, alternateId, callbackNumber,
htmlLinkUrl, htmlLinkName, orgNameOverride):
Room 101, HQ Building, , Floor 1 East, , +12175550100, , ,
Only name and building are required (building may be blank to place the
location directly under the organization). Header row is skipped.

Logs: ../_logs/<timestamp>-locations_add.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from redskyCommon import connect, offer_csv_template, read_csv_rows, log_result

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'locations_add.csv'
CSV_HEADER = ('name', 'building', 'fullAddress', 'info', 'alternateId', 'callbackNumber',
          'htmlLinkUrl', 'htmlLinkName', 'orgNameOverride')
OPTIONAL_FIELDS = ('full_address', 'info', 'alternate_id', 'callback_number',
                   'html_link_url', 'html_link_name', 'org_name_override')


def add_location(redsky, logger, name, parent_id, **optional):
    """
    Add a location to RedSky.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        name (string): Location name
        parent_id (string): Building id (or org id for the no-building case)
        **optional: full_address, info, alternate_id, callback_number,
            html_link_url, html_link_name, org_name_override
    """
    logger.info('Adding location %s', name)
    result = redsky.add_location(name, parent_id, **optional)
    ok = log_result(logger, name, result)
    for candidate in result.get('candidates', []):
        logger.error('  Candidate address: %s', candidate)
    return ok


def select_building(buildings):
    """Numbered building menu. Returns a building id, the org marker '', or None to cancel."""
    print('\nBuildings:')
    print('  0. (none - place directly under the organization)')
    for i, b in enumerate(buildings, 1):
        print(f'  {i}. {b.get("name", "")}')
    while True:
        choice = input(f'Select Building [0-{len(buildings)}]: ').strip()
        if choice.isdigit() and 0 <= int(choice) <= len(buildings):
            return '' if int(choice) == 0 else buildings[int(choice) - 1]['id']
        print('Invalid selection.')


def run_single_location(redsky, logger, buildings):
    """
    Add a single location
    """
    parent_id = select_building(buildings) or redsky.org_id
    name = input('Location Name: ').strip()
    if not name:
        logger.error('Location Name is required.')
        return
    optional = {
        'full_address': input('Full Address (optional): ').strip(),
        'info': input('Info (optional): ').strip(),
        'alternate_id': input('Alternate ID (optional): ').strip(),
        'callback_number': input('Callback Number (optional): ').strip(),
        'html_link_url': input('HTML Link URL (optional): ').strip(),
        'html_link_name': input('HTML Link Name (optional): ').strip(),
        'org_name_override': input('Org Name Override (optional): ').strip(),
    }
    add_location(redsky, logger, name, parent_id, **optional)


def run_csv_file(redsky, logger, csv_file_path, buildings):
    """
    Bulk add locations from CSV
    """
    print('\nCSV Must have header row and must contain only 1 location per row')
    print('Field Order: name, building, fullAddress, info, alternateId, callbackNumber, '
          'htmlLinkUrl, htmlLinkName, orgNameOverride')
    building_ids = {b.get('name', '').strip().lower(): b['id'] for b in buildings}
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        name, building_name = f[0], f[1]
        if not name:
            logger.error('Skipping line %d, name is required', line)
            failed += 1
            continue
        if building_name:
            parent_id = building_ids.get(building_name.lower())
            if not parent_id:
                logger.error('Skipping %s (line %d), unknown building: %s', name, line, building_name)
                failed += 1
                continue
        else:
            parent_id = redsky.org_id
        optional = dict(zip(OPTIONAL_FIELDS, f[2:9]))
        if add_location(redsky, logger, name, parent_id, **optional):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-locations_add.log"
    logger = setup_logger(log_file)
    logger.info("Locations Add - Started")

    redsky = connect(logger)
    try:
        buildings = redsky.list_buildings()
    except Exception as e:
        logger.error('Unable to load buildings from RedSky: %s', e)
        sys.exit(1)
    logger.info('Loaded %d building(s)', len(buildings))

    use_csv = prompt_yes_no('Use CSV?', default=False)
    if use_csv:
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Locations Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 location per row')
        print('Field Order: name, building, fullAddress, info, alternateId, callbackNumber, '
              'htmlLinkUrl, htmlLinkName, orgNameOverride')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file, buildings)
    else:
        run_single_location(redsky, logger, buildings)

    logger.info("Locations Add - Completed")
