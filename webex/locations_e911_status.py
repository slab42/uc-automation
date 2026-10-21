#!/usr/bin/env python3
# TITLE: Locations List with E911 Status

"""
List all Webex Calling locations with their RedSky E911 status.

For every location the following values are shown:
    complianceStatus, integrationEnabled, routingEnabled

Uses the Calling admin API (spark-admin:telephony_config_read):
    GET /v1/telephony/config/locations
    GET /v1/telephony/config/locations/{locationId}/redSky/status  (complianceStatus)
    GET /v1/telephony/config/locations/{locationId}/redSky         (integrationEnabled, routingEnabled)

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Output: table on screen and _DATA/reports/locations_e911_status_<timestamp>.csv
Logs: ../_logs/<timestamp>-locations_e911_status.log
"""

import warnings
warnings.simplefilter('ignore')

import csv
import getpass
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from setup.logger import setup_logger
from setup.env_loader import CredentialsLoader

API_BASE = 'https://webexapis.com/v1'
ME_URL = f'{API_BASE}/people/me'
LOCATIONS_URL = f'{API_BASE}/telephony/config/locations'
MAX_WORKERS = 5
CSV_HEADER = ['Location', 'Compliance Status', 'Integration Enabled', 'Routing Enabled']


def get_token(logger):
    """Return a Webex token from credentials.env, or prompt (hidden) if missing."""
    token = ''
    try:
        loader = CredentialsLoader(os.path.join(BASE_DIR, '.env', 'credentials.env'))
        creds = loader.get_webex_credentials('default')
        if creds:
            token = (creds.get('api_token') or '').strip()
    except Exception as e:
        logger.debug(f'Unable to read stored Webex credentials: {e}')

    while True:
        if not token:
            token = getpass.getpass('Enter Webex access token: ').strip()
        response = requests.get(ME_URL, headers={'Authorization': f'Bearer {token}'}, timeout=10)
        if response.status_code == 200:
            logger.info('Access token validated.')
            return token
        logger.error(f'Access token rejected (HTTP {response.status_code}). Please try again.')
        token = ''


def api_get(url, headers, logger, params=None):
    """GET a URL; return parsed JSON or None on error."""
    response = requests.get(url, headers=headers, params=params, timeout=30)
    if response.status_code != 200:
        logger.error(f'GET {url} failed: HTTP {response.status_code} {response.text}')
        return None
    return response.json()


def get_locations(headers, logger):
    """Return all telephony locations."""
    locations = []
    start = 0
    while True:
        data = api_get(LOCATIONS_URL, headers, logger, params={'max': 100, 'start': start})
        if not data:
            break
        page = data.get('locations', [])
        locations.extend(page)
        if len(page) < 100:
            break
        start += 100
    return locations


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-locations_e911_status.log'
    logger = setup_logger(log_file)
    logger.info('Locations List with E911 Status - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    locations = get_locations(headers, logger)
    logger.info(f'Retrieved {len(locations)} location(s).')

    def fetch_row(loc):
        status = api_get(f'{LOCATIONS_URL}/{loc["id"]}/redSky/status', headers, logger)
        params = api_get(f'{LOCATIONS_URL}/{loc["id"]}/redSky', headers, logger)
        return [
            loc.get('name', ''),
            status.get('complianceStatus', '') if status else 'ERROR',
            params.get('integrationEnabled', '') if params else 'ERROR',
            params.get('routingEnabled', '') if params else 'ERROR',
        ]

    locations = sorted(locations, key=lambda l: l.get('name', '').lower())
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        rows = list(pool.map(fetch_row, locations))

    if rows:
        widths = [max(len(str(r[i])) for r in rows + [CSV_HEADER]) for i in range(len(CSV_HEADER))]
        fmt = '  '.join(f'{{:<{w}}}' for w in widths)
        print()
        print(fmt.format(*CSV_HEADER))
        print(fmt.format(*['-' * w for w in widths]))
        for row in rows:
            print(fmt.format(*[str(c) for c in row]))
        print()

    report_dir = os.path.join(BASE_DIR, '_DATA', 'reports')
    os.makedirs(report_dir, exist_ok=True)
    out_file = os.path.join(report_dir, f'locations_e911_status_{timestamp}.csv')
    with open(out_file, 'w', newline='', encoding='utf8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)
    logger.info(f'Report written to {out_file}')
    logger.info('Locations List with E911 Status - Completed')


if __name__ == '__main__':
    main()
