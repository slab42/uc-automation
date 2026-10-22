#!/usr/bin/env python3
# TITLE: Networking Public IP Add

"""
Add public (trusted) IP ranges to RedSky (E911), individually or from a list
in CSV. Public ranges are the egress addresses RedSky uses to recognize that a
client is on a known network.

Usage:
    python3 networking_public_ip_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add ranges from a CSV file,
        or 'n' (default) to add a single range.

    If 'n' (single range):
        IP Address Low: first address in the range
        IP Address High: last address in the range (same as low for one address)
        Description: optional

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/networking_public_ip_add.csv)

CSV format (ipAddressLow, ipAddressHigh, description):
203.0.113.10, 203.0.113.20, HQ internet egress
description is optional. Header row is skipped.

Logs: ../_logs/<timestamp>-networking_public_ip_add.log
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

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'networking_public_ip_add.csv'
CSV_HEADER = ('ipAddressLow', 'ipAddressHigh', 'description')


def add_public_ip(redsky, logger, ip_low, ip_high, description=''):
    """
    Add a public IP range.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        ip_low (string): First address
        ip_high (string): Last address
        description (string): Optional description
    """
    logger.info('Adding public IP range %s - %s', ip_low, ip_high)
    return log_result(logger, f'{ip_low}-{ip_high}', redsky.add_public_ip_range(ip_low, ip_high, description))


def run_single(redsky, logger):
    """
    Add a single public IP range
    """
    ip_low = input('IP Address Low: ').strip()
    ip_high = input('IP Address High: ').strip()
    description = input('Description (optional): ').strip()
    if not ip_low or not ip_high:
        logger.error('IP Address Low and IP Address High are required.')
        return
    add_public_ip(redsky, logger, ip_low, ip_high, description)


def run_csv_file(redsky, logger, csv_file_path):
    """
    Bulk add public IP ranges from CSV
    """
    print('\nCSV Must have header row and must contain only 1 range per row')
    print('Field Order: ipAddressLow, ipAddressHigh, description (optional)')
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        if not f[0] or not f[1]:
            logger.error('Skipping line %d, ipAddressLow and ipAddressHigh are required', line)
            failed += 1
        elif add_public_ip(redsky, logger, f[0], f[1], f[2]):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-networking_public_ip_add.log"
    logger = setup_logger(log_file)
    logger.info("Networking Public IP Add - Started")

    redsky = connect(logger)

    if prompt_yes_no('Use CSV?', default=False):
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Networking Public IP Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 range per row')
        print('Field Order: ipAddressLow, ipAddressHigh, description (optional)')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file)
    else:
        run_single(redsky, logger)

    logger.info("Networking Public IP Add - Completed")
