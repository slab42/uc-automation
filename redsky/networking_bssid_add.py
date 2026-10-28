#!/usr/bin/env python3
# TITLE: Networking BSSID Add

"""
Add wireless access point BSSIDs to RedSky (E911) and tie each to a Location,
individually or from a list in CSV. A client that sees the BSSID is placed at
that Location.

Usage:
    python3 networking_bssid_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add BSSIDs from a CSV file,
        or 'n' (default) to add a single BSSID.

    If 'n' (single BSSID):
        BSSID: access point MAC address, e.g. 00:1A:2B:3C:4D:5E
        Location: Location name, or 'Building / Location' when the name is
            used in more than one Building
        Description: optional
        BSSID Masking?: (y/n) optional, leave at default to not set it

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/networking_bssid_add.csv)

Location is matched by name, case-insensitively. A row whose Location is
unknown (or ambiguous across Buildings) is skipped and logged.

CSV format (bssid, location, description, masking):
00:1A:2B:3C:4D:5E, HQ Building / Room 101, AP-101, yes
description and masking are optional. masking accepts yes/no/true/false/1/0;
blank leaves it unset. Header row is skipped.

Logs: ../_logs/<timestamp>-networking_bssid_add.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from redskyCommon import connect, offer_csv_template, load_location_map, resolve_location, read_csv_rows, log_result, parse_bool, LOCATION_HELP

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'networking_bssid_add.csv'
CSV_HEADER = ('bssid', 'location', 'description', 'masking')


def add_bssid(redsky, logger, location_map, bssid, location, description='', masking=None):
    """
    Add a BSSID tied to a Location.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        location_map: lookup from load_location_map()
        bssid (string): Access point MAC address
        location (string): Location name or 'Building / Location'
        description (string): Optional description
        masking (bool): Optional BSSID masking flag
    """
    location_id, error = resolve_location(location_map, location)
    if error:
        logger.error('%s: %s', bssid, error)
        return False
    logger.info('Adding BSSID %s at %s', bssid, location)
    return log_result(logger, bssid, redsky.add_bssid(bssid, location_id, description, masking))


def run_single(redsky, logger, location_map):
    """
    Add a single BSSID
    """
    print(LOCATION_HELP)
    bssid = input('BSSID: ').strip()
    location = input('Location: ').strip()
    description = input('Description (optional): ').strip()
    masking = prompt_yes_no('BSSID Masking?', default=False) or None
    if not (bssid and location):
        logger.error('BSSID and Location are required.')
        return
    add_bssid(redsky, logger, location_map, bssid, location, description, masking)


def run_csv_file(redsky, logger, csv_file_path, location_map):
    """
    Bulk add BSSIDs from CSV
    """
    print('\nCSV Must have header row and must contain only 1 BSSID per row')
    print('Field Order: bssid, location, description (optional), masking (optional)')
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        if not (f[0] and f[1]):
            logger.error('Skipping line %d, bssid and location are required', line)
            failed += 1
        elif add_bssid(redsky, logger, location_map, f[0], f[1], f[2], parse_bool(f[3])):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-networking_bssid_add.log"
    logger = setup_logger(log_file)
    logger.info("Networking BSSID Add - Started")

    redsky = connect(logger)
    location_map = load_location_map(redsky, logger)

    if prompt_yes_no('Use CSV?', default=False):
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Networking BSSID Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 BSSID per row')
        print('Field Order: bssid, location, description (optional), masking (optional)')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file, location_map)
    else:
        run_single(redsky, logger, location_map)

    logger.info("Networking BSSID Add - Completed")
