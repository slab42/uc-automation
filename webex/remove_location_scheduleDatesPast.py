#!/usr/bin/env python3
# TITLE: Location Schedule Dates Past Remove

"""
Find and remove past events from Webex Calling location holiday schedules.

Prompts to process all locations, or to search for locations by name text
(every location containing the text is processed). For each location, every
holiday schedule is read and events whose end date is before today are listed:
    Location - Schedule - Event Name - Dates
Recurring events and business hours schedules are never listed.

You are then offered: [A]ll to delete every listed event, [I]ndividual to be
asked about each event, or [N]one to exit without changes.

Uses the Calling admin API (spark-admin:telephony_config_read / _write):
    GET    /v1/telephony/config/locations
    GET    /v1/telephony/config/locations/{locationId}/schedules
    GET    /v1/telephony/config/locations/{locationId}/schedules/holidays/{scheduleId}
    DELETE /v1/telephony/config/locations/{locationId}/schedules/holidays/{scheduleId}/events/{eventId}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Logs: ../_logs/<timestamp>-remove_location_scheduleDatesPast.log
"""

import warnings
warnings.simplefilter('ignore')

import os
import sys
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from export_location_holidaySchedule import (
    LOCATIONS_URL, get_token, api_get, find_locations, format_date,
)

SCHEDULE_TYPE = 'holidays'


def list_all_locations(headers, logger):
    """Return every telephony location (empty search text matches all)."""
    return find_locations(headers, '', logger)


def find_past_events(location, headers, today, logger):
    """Return a list of past one-time holiday events at the location."""
    data = api_get(f'{LOCATIONS_URL}/{location["id"]}/schedules', headers, logger)
    found = []
    for sched in (data or {}).get('schedules', []):
        if sched.get('type') != SCHEDULE_TYPE:
            continue
        detail = api_get(f'{LOCATIONS_URL}/{location["id"]}/schedules/{SCHEDULE_TYPE}/{sched["id"]}',
                         headers, logger)
        if detail is None:
            logger.error(f'Unable to read schedule "{sched.get("name")}" at {location["name"]}.')
            continue
        for e in detail.get('events', []):
            if e.get('recurrence'):
                continue
            start = e.get('startDate') or ''
            end = e.get('endDate') or start
            if end and end < today:
                found.append({'location': location, 'schedule': sched, 'event': e,
                              'start': start, 'end': end})
    return found


def dates_text(item):
    start, end = format_date(item['start']), format_date(item['end'])
    return start if start == end else f'{start} - {end}'


def label(item):
    return (f'{item["location"]["name"]} - {item["schedule"]["name"]} - '
            f'{item["event"].get("name", "")} - {dates_text(item)}')


def delete_event(item, headers, logger):
    url = (f'{LOCATIONS_URL}/{item["location"]["id"]}/schedules/{SCHEDULE_TYPE}/'
           f'{item["schedule"]["id"]}/events/{item["event"]["id"]}')
    response = requests.delete(url, headers=headers, timeout=30)
    if response.status_code not in (200, 204):
        logger.error(f'Delete failed for {label(item)}: HTTP {response.status_code} {response.text}')
        return False
    logger.info(f'Deleted: {label(item)}')
    return True


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-remove_location_scheduleDatesPast.log'
    logger = setup_logger(log_file)
    logger.info('Location Schedule Dates Past Remove - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    # Choose locations: all, or by search text
    if prompt_yes_no('Process all locations?', default=True):
        locations = list_all_locations(headers, logger)
    else:
        locations = []
        while not locations:
            search = input('Enter text to search for the location: ').strip()
            if not search:
                continue
            locations = find_locations(headers, search, logger)
            if not locations:
                logger.warning(f'No locations match "{search}".')
                if not prompt_yes_no('Search again?', default=True):
                    logger.info('Location Schedule Dates Past Remove - Completed')
                    return
    logger.info(f'Checking {len(locations)} location(s).')

    # Gather past events
    today = datetime.now().strftime('%Y-%m-%d')
    items = []
    for location in locations:
        items.extend(find_past_events(location, headers, today, logger))

    if not items:
        logger.info('No past schedule events found.')
        logger.info('Location Schedule Dates Past Remove - Completed')
        return

    print('\nLocation - Schedule - Event Name - Dates')
    for i, item in enumerate(items, 1):
        print(f'  {i}. {label(item)}')
    logger.info(f'Found {len(items)} past event(s).')

    # Offer deletion
    while True:
        choice = input('\nDelete [A]ll, [I]ndividual, [N]one [N]: ').strip().lower() or 'n'
        if choice in ('a', 'i', 'n'):
            break
        print('Invalid selection.')

    if choice == 'n':
        logger.info('No changes made.')
        logger.info('Location Schedule Dates Past Remove - Completed')
        return

    if choice == 'i':
        selected = [item for item in items if prompt_yes_no(f'Delete "{label(item)}"?', default=False)]
    else:
        selected = items

    ok = sum(1 for item in selected if delete_event(item, headers, logger))
    logger.info(f'Done: {ok} deleted, {len(selected) - ok} failed, {len(items) - len(selected)} skipped.')
    logger.info('Location Schedule Dates Past Remove - Completed')


if __name__ == '__main__':
    main()
