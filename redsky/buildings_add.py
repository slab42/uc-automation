#!/usr/bin/env python3
# TITLE: Buildings Add

"""
Add Buildings to RedSky (E911), individually or from a list in CSV.

Usage:
    python3 buildings_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add buildings from a CSV file,
        or 'n' (default) to add a single building.

    If 'n' (single building):
        Building Name: name shown in RedSky
        Full Address: street address; RedSky validates and normalizes it
        Supplemental Data: optional extra location detail

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/buildings_add.csv)

RedSky validates every address. If an address is ambiguous (several candidate
matches) or invalid, the building is not created and the row is logged as an
error so the address can be corrected and the row retried.

CSV format (name, fullAddress, supplementalData):
HQ Building, "100 Main St, Springfield, IL 62701", Floor 1-5
supplementalData is optional. Header row is skipped.

Logs: ../_logs/<timestamp>-buildings_add.log
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

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'buildings_add.csv'
CSV_HEADER = ('name', 'fullAddress', 'supplementalData')


def add_building(redsky, logger, name, full_address, supplemental_data=''):
    """
    Add a building to RedSky.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        name (string): Building name
        full_address (string): Street address to validate and store
        supplemental_data (string): Optional extra location detail
    """
    logger.info('Adding building %s at %s', name, full_address)
    result = redsky.add_building(name, full_address, supplemental_data)
    ok = log_result(logger, name, result)
    for candidate in result.get('candidates', []):
        logger.error('  Candidate address: %s', candidate)
    return ok


def run_single_building(redsky, logger):
    """
    Add a single building
    """
    name = input('Building Name: ').strip()
    full_address = input('Full Address: ').strip()
    supplemental_data = input('Supplemental Data (optional): ').strip()
    if not name or not full_address:
        logger.error('Building Name and Full Address are required.')
        return
    add_building(redsky, logger, name, full_address, supplemental_data)


def run_csv_file(redsky, logger, csv_file_path):
    """
    Bulk add buildings from CSV
    """
    print('\nCSV Must have header row and must contain only 1 building per row')
    print('Field Order: name, fullAddress, supplementalData (optional)')
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        if not (f[0] and f[1]):
            logger.error('Skipping line %d, expected at least 2 fields (name, fullAddress)', line)
            failed += 1
        elif add_building(redsky, logger, f[0], f[1], f[2]):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-buildings_add.log"
    logger = setup_logger(log_file)
    logger.info("Buildings Add - Started")

    redsky = connect(logger)

    use_csv = prompt_yes_no('Use CSV?', default=False)
    if use_csv:
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Buildings Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 building per row')
        print('Field Order: name, fullAddress, supplementalData (optional)')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file)
    else:
        run_single_building(redsky, logger)

    logger.info("Buildings Add - Completed")
