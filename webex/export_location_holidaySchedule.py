#!/usr/bin/env python3
# TITLE: Location Holiday Schedule Export

"""
Export a Webex Calling location schedule (holidays) to CSV.

Prompts to export (Y/n), then for the source location text to search for.
If more than one location matches, a numbered list is offered. After the
location is chosen, its schedules are listed and one is selected. The events
of that schedule are written to a CSV in the holiday_schedule.csv template
format, ready to be used to create the schedule at another location.

Uses the Calling admin API (spark-admin:telephony_config_read):
    GET /v1/telephony/config/locations
    GET /v1/telephony/config/locations/{locationId}/schedules
    GET /v1/telephony/config/locations/{locationId}/schedules/{type}/{scheduleId}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Output CSV columns (see _DATA/examples/holiday_schedule.csv.EXAMPLE):
    Name,Event action,Event name,Event start date,Event end date
    Dates are written as M/D/YY. Event action is always ADD.

Output: _DATA/holiday_schedule_<location>_<schedule>.csv
Logs: ../_logs/<timestamp>-export_location_holidaySchedule.log
"""

import warnings
warnings.simplefilter('ignore')

import csv
import getpass
import os
import re
import sys
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.env_loader import CredentialsLoader

API_BASE = 'https://webexapis.com/v1'
ME_URL = f'{API_BASE}/people/me'
LOCATIONS_URL = f'{API_BASE}/telephony/config/locations'
CSV_HEADER = ['Name', 'Event action', 'Event name',
              'Event start date', 'Event end date']


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


def select_from_list(items, label_fn, noun):
    """Numbered selection prompt; returns the chosen item."""
    print(f'\nSelect a {noun}:')
    for i, item in enumerate(items, 1):
        print(f'  {i}. {label_fn(item)}')
    while True:
        choice = input(f'Select {noun} [1-{len(items)}]: ').strip()
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1]
        print('Invalid selection.')


def find_locations(headers, search, logger):
    """Return all telephony locations whose name contains the search text."""
    locations = []
    start = 0
    while True:
        data = api_get(LOCATIONS_URL, headers, logger, params={'max': 100, 'start': start})
        if not data:
            return locations
        page = data.get('locations', [])
        locations.extend(page)
        if len(page) < 100:
            break
        start += 100
    return [loc for loc in locations if search.lower() in loc.get('name', '').lower()]


def format_date(value):
    """Convert YYYY-MM-DD to M/D/YY (matches the template)."""
    try:
        d = datetime.strptime(value, '%Y-%m-%d')
        return f'{d.month}/{d.day}/{d.strftime("%y")}'
    except (TypeError, ValueError):
        return value or ''


def safe_name(text):
    return re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_')


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-export_location_holidaySchedule.log'
    logger = setup_logger(log_file)
    logger.info('Export Location Holiday Schedule - Started')

    if not prompt_yes_no('Export a location holiday schedule?', default=True):
        logger.info('Export declined by user.')
        logger.info('Export Location Holiday Schedule - Completed')
        return

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    # Find the source location
    location = None
    while location is None:
        search = input('Enter text to search for the source location: ').strip()
        if not search:
            continue
        matches = find_locations(headers, search, logger)
        if not matches:
            logger.warning(f'No locations match "{search}".')
            if not prompt_yes_no('Search again?', default=True):
                logger.info('Export Location Holiday Schedule - Completed')
                return
        elif len(matches) == 1:
            location = matches[0]
        else:
            location = select_from_list(matches, lambda l: l['name'], 'location')
    logger.info(f'Source location: {location["name"]}')

    # List schedules (holidays and business hours) for the location
    data = api_get(f'{LOCATIONS_URL}/{location["id"]}/schedules', headers, logger)
    schedules = (data or {}).get('schedules', [])
    if not schedules:
        logger.warning(f'No schedules found for {location["name"]}.')
        logger.info('Export Location Holiday Schedule - Completed')
        return
    schedule = select_from_list(
        schedules, lambda s: f'{s["name"]} ({s.get("type", "")})', 'schedule')
    logger.info(f'Selected schedule: {schedule["name"]} ({schedule.get("type", "")})')

    # Get events
    detail = api_get(
        f'{LOCATIONS_URL}/{location["id"]}/schedules/{schedule["type"]}/{schedule["id"]}',
        headers, logger)
    if detail is None:
        logger.error('Unable to retrieve schedule details.')
        logger.info('Export Location Holiday Schedule - Completed')
        return
    events = detail.get('events', [])
    logger.info(f'Retrieved {len(events)} event(s).')

    out_file = os.path.join(
        BASE_DIR, '_DATA',
        f'holiday_schedule_{safe_name(location["name"])}_{safe_name(schedule["name"])}.csv')
    with open(out_file, 'w', newline='', encoding='utf8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for event in events:
            start = event.get('startDate', '')
            writer.writerow([
                schedule['name'], 'ADD', event.get('name', ''),
                format_date(start), format_date(event.get('endDate') or start),
            ])
    logger.info(f'Exported {len(events)} event(s) to {out_file}')
    logger.info('Export Location Holiday Schedule - Completed')


if __name__ == '__main__':
    main()
