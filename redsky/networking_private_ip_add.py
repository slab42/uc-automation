#!/usr/bin/env python3
# TITLE: Networking Private IP Add

"""
Add private IP ranges to RedSky (E911) and tie each to a Location, individually
or from a list in CSV. A client whose address falls in the range is placed at
that Location.

Usage:
    python3 networking_private_ip_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add ranges from a CSV file,
        or 'n' (default) to add a single range.

    If 'n' (single range):
        IP Address Low: first address in the range
        IP Address High: last address in the range (same as low for one address)
        Location: Location name, or 'Building / Location' when the name is
            used in more than one Building
        Description: optional

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/networking_private_ip_add.csv)

Location is matched by name, case-insensitively. A row whose Location is
unknown (or ambiguous across Buildings) is skipped and logged.

CSV format (ipAddressLow, ipAddressHigh, location, description):
10.10.1.0, 10.10.1.255, HQ Building / Room 101, Floor 1 data VLAN
description is optional. Header row is skipped.

Logs: ../_logs/<timestamp>-networking_private_ip_add.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from redskyCommon import connect, offer_csv_template, load_location_map, resolve_location, read_csv_rows, log_result, LOCATION_HELP

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'networking_private_ip_add.csv'
CSV_HEADER = ('ipAddressLow', 'ipAddressHigh', 'location', 'description')


def add_private_ip(redsky, logger, location_map, ip_low, ip_high, location, description=''):
    """
    Add a private IP range tied to a Location.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        location_map: lookup from load_location_map()
        ip_low (string): First address
        ip_high (string): Last address
        location (string): Location name or 'Building / Location'
        description (string): Optional description
    """
    location_id, error = resolve_location(location_map, location)
    if error:
        logger.error('%s-%s: %s', ip_low, ip_high, error)
        return False
    logger.info('Adding private IP range %s - %s at %s', ip_low, ip_high, location)
    return log_result(logger, f'{ip_low}-{ip_high}',
                      redsky.add_ip_range(ip_low, ip_high, location_id, description))


def run_single(redsky, logger, location_map):
    """
    Add a single private IP range
    """
    print(LOCATION_HELP)
    ip_low = input('IP Address Low: ').strip()
    ip_high = input('IP Address High: ').strip()
    location = input('Location: ').strip()
    description = input('Description (optional): ').strip()
    if not (ip_low and ip_high and location):
        logger.error('IP Address Low, IP Address High and Location are required.')
        return
    add_private_ip(redsky, logger, location_map, ip_low, ip_high, location, description)


def run_csv_file(redsky, logger, csv_file_path, location_map):
    """
    Bulk add private IP ranges from CSV
    """
    print('\nCSV Must have header row and must contain only 1 range per row')
    print('Field Order: ipAddressLow, ipAddressHigh, location, description (optional)')
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        if not (f[0] and f[1] and f[2]):
            logger.error('Skipping line %d, ipAddressLow, ipAddressHigh and location are required', line)
            failed += 1
        elif add_private_ip(redsky, logger, location_map, f[0], f[1], f[2], f[3]):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-networking_private_ip_add.log"
    logger = setup_logger(log_file)
    logger.info("Networking Private IP Add - Started")

    redsky = connect(logger)
    location_map = load_location_map(redsky, logger)

    if prompt_yes_no('Use CSV?', default=False):
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Networking Private IP Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 range per row')
        print('Field Order: ipAddressLow, ipAddressHigh, location, description (optional)')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file, location_map)
    else:
        run_single(redsky, logger, location_map)

    logger.info("Networking Private IP Add - Completed")
