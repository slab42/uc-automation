#!/usr/bin/env python3
# TITLE: Locations Disable RedSky

"""
Opt Webex Calling locations out of RedSky Emergency Calling.

The script asks whether to use a CSV of location names:
    Yes - only the locations named in the CSV are opted out. Names are matched
          case-insensitively; names not found in Webex are logged and skipped.
    No  - every Webex Calling location is opted out.
A summary is shown and confirmation is requested before any change is made.

Uses the Calling admin API (spark-admin:telephony_config_write):
    GET /v1/telephony/config/locations
    PUT /v1/telephony/config/locations/{locationId}/redSky/status
        body: {"complianceStatus": "OPTED_OUT"}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Input CSV columns (see _DATA/examples/locations_DisableRedSky.csv.EXAMPLE):
    Location
    Header row is skipped. Extra columns are ignored.

Logs: ../_logs/<timestamp>-locations_DisableRedSky.log
"""

import warnings
warnings.simplefilter('ignore')

import csv
import os
import sys
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from locations_e911_status import get_token, get_locations, LOCATIONS_URL

DEFAULT_CSV = os.path.join(BASE_DIR, '_DATA', 'locations_DisableRedSky.csv')


def load_location_names(path):
    """Return the first column of each CSV row after the header."""
    names = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = csv.reader(f)
        next(rows, None)
        for row in rows:
            if row and row[0].strip():
                names.append(row[0].strip())
    return names


def opt_out(location, headers, logger):
    """Set a location's RedSky complianceStatus to OPTED_OUT. Return True on success."""
    url = f'{LOCATIONS_URL}/{location["id"]}/redSky/status'
    try:
        response = requests.put(url, headers=headers, json={'complianceStatus': 'OPTED_OUT'}, timeout=30)
    except requests.RequestException as e:
        logger.error(f'Failed for {location["name"]}: {e}')
        return False
    if response.status_code in (200, 204):
        logger.info(f'Opted out: {location["name"]}')
        return True
    logger.error(f'Failed for {location["name"]}: HTTP {response.status_code} {response.text}')
    return False


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-locations_DisableRedSky.log'
    logger = setup_logger(log_file)
    logger.info('Locations Disable RedSky - Started')

    token = get_token(logger)
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    locations = get_locations(headers, logger)
    logger.info(f'Retrieved {len(locations)} location(s).')

    if prompt_yes_no('Use a CSV of location names?', default=True):
        csv_path = input(f'Path to location CSV [{DEFAULT_CSV}]: ').strip() or DEFAULT_CSV
        if not os.path.isfile(csv_path):
            logger.error(f'CSV file not found: {csv_path}')
            return
        names = load_location_names(csv_path)
        by_name = {loc.get('name', '').lower(): loc for loc in locations}
        targets = []
        for name in names:
            loc = by_name.get(name.lower())
            if loc:
                targets.append(loc)
            else:
                logger.warning(f'Location not found in Webex, skipping: {name}')
        logger.info(f'{len(targets)} of {len(names)} CSV location(s) matched.')
    else:
        targets = locations

    if not targets:
        logger.info('No locations to process.')
        logger.info('Locations Disable RedSky - Completed')
        return

    print('\nLocations to opt out of Emergency Calling:')
    for loc in targets:
        print(f'  {loc["name"]}')
    print()
    if not prompt_yes_no(f'Opt out {len(targets)} location(s)?', default=False):
        logger.info('Cancelled by user.')
        return

    succeeded = sum(opt_out(loc, headers, logger) for loc in targets)
    logger.info(f'Opted out {succeeded} of {len(targets)} location(s).')
    logger.info('Locations Disable RedSky - Completed')


if __name__ == '__main__':
    main()
