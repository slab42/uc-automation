#!/usr/bin/env python3
# TITLE: Location Schedule Copy

"""
Copy a Webex Calling location schedule (holidays or business hours) to other locations.

Prompts for text to search for the source location. If more than one location
matches, a numbered list is offered. The location's schedules are then listed
and one is selected. Finally, choose where to copy it:
  A = all other locations
  S = search for a single target location
  N = exit without copying
A summary is shown and confirmation is requested before any change is made.
If the target location already has a schedule of the same type and name, its
events are updated instead: events missing from the target are added, and events
with the same name but different details are updated. Events that exist only at
the target are left alone.

Uses the Calling admin API (spark-admin:telephony_config_read / _write):
    GET  /v1/telephony/config/locations
    GET  /v1/telephony/config/locations/{locationId}/schedules
    GET  /v1/telephony/config/locations/{locationId}/schedules/{type}/{scheduleId}
    POST /v1/telephony/config/locations/{locationId}/schedules
    POST /v1/telephony/config/locations/{locationId}/schedules/{type}/{scheduleId}/events
    PUT  /v1/telephony/config/locations/{locationId}/schedules/{type}/{scheduleId}/events/{eventId}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Logs: ../_logs/<timestamp>-copy_location_schedule.log
"""

import warnings
warnings.simplefilter('ignore')

import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from export_location_holidaySchedule import (
    LOCATIONS_URL, get_token, api_get, select_from_list, find_locations,
)
from update_location_holidayschedule import api_send

TITLE = 'Copy Location Schedule'


def choose_location(headers, prompt, logger):
    """Search for a location by text; return the chosen location or None if the user gives up."""
    while True:
        search = input(prompt).strip()
        if not search:
            continue
        matches = find_locations(headers, search, logger)
        if not matches:
            logger.warning(f'No locations match "{search}".')
            if not prompt_yes_no('Search again?', default=True):
                return None
        elif len(matches) == 1:
            return matches[0]
        else:
            return select_from_list(matches, lambda l: l['name'], 'location')


def list_schedules(location, headers, logger):
    data = api_get(f'{LOCATIONS_URL}/{location["id"]}/schedules', headers, logger)
    return (data or {}).get('schedules', [])


def copy_body(schedule, detail):
    """Build the create body from the source schedule, dropping server-assigned ids."""
    events = []
    for event in detail.get('events', []):
        events.append({k: v for k, v in event.items() if k != 'id'})
    return {'type': schedule['type'], 'name': schedule['name'], 'events': events}


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-copy_location_schedule.log'
    logger = setup_logger(log_file)
    logger.info(f'{TITLE} - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json',
               'Content-Type': 'application/json'}

    # Source location
    source = choose_location(headers, 'Enter text to search for the source location: ', logger)
    if source is None:
        logger.info(f'{TITLE} - Completed')
        return
    logger.info(f'Source location: {source["name"]}')

    # Source schedule
    schedules = list_schedules(source, headers, logger)
    if not schedules:
        logger.warning(f'No schedules found for {source["name"]}.')
        logger.info(f'{TITLE} - Completed')
        return
    schedule = select_from_list(
        schedules, lambda s: f'{s["name"]} ({s.get("type", "")})', 'schedule')
    logger.info(f'Selected schedule: {schedule["name"]} ({schedule.get("type", "")})')

    detail = api_get(f'{LOCATIONS_URL}/{source["id"]}/schedules/{schedule["type"]}/{schedule["id"]}',
                     headers, logger)
    if detail is None:
        logger.error('Unable to retrieve schedule details.')
        logger.info(f'{TITLE} - Completed')
        return
    body = copy_body(schedule, detail)
    logger.info(f'Schedule has {len(body["events"])} event(s).')

    # Targets
    while True:
        choice = input('Copy to all locations (A), search for one (S), or exit (N)? [A/S/N]: ').strip().upper()
        if choice in ('A', 'S', 'N'):
            break
        print('Please enter A, S or N.')
    if choice == 'N':
        logger.info('Copy declined by user.')
        logger.info(f'{TITLE} - Completed')
        return
    if choice == 'A':
        targets = find_locations(headers, '', logger)
    else:
        target = choose_location(headers, 'Enter text to search for the target location: ', logger)
        targets = [target] if target else []
    targets = [t for t in targets if t['id'] != source['id']]
    if not targets:
        logger.warning('No target locations selected.')
        logger.info(f'{TITLE} - Completed')
        return

    print(f'\nCopy "{schedule["name"]}" ({schedule["type"]}) from {source["name"]} to '
          f'{len(targets)} location(s):')
    for t in targets:
        print(f'  - {t["name"]}')
    if not prompt_yes_no('Apply these changes?', default=False):
        logger.info('Changes declined by user.')
        logger.info(f'{TITLE} - Completed')
        return

    created = updated = unchanged = failed = 0
    for t in targets:
        base = f'{LOCATIONS_URL}/{t["id"]}/schedules'
        existing = api_get(base, headers, logger)
        if existing is None:
            failed += 1
            continue
        match = next((s for s in existing.get('schedules', [])
                      if s.get('type') == schedule['type']
                      and s.get('name', '').lower() == schedule['name'].lower()), None)
        if match is None:
            if api_send('POST', base, headers, logger, body) is None:
                failed += 1
            else:
                logger.info(f'[{t["name"]}] Created "{schedule["name"]}".')
                created += 1
            continue

        # Schedule exists: add missing events, update events that differ (none are removed)
        target_detail = api_get(f'{base}/{schedule["type"]}/{match["id"]}', headers, logger)
        if target_detail is None:
            failed += 1
            continue
        current = {e.get('name', '').lower(): e for e in target_detail.get('events', [])}
        changes = 0
        for event in body['events']:
            key = event.get('name', '').lower()
            cur = current.get(key)
            if cur is None:
                result = api_send('POST', f'{base}/{schedule["type"]}/{match["id"]}/events',
                                  headers, logger, event)
                action = 'Added'
            elif {k: v for k, v in cur.items() if k != 'id'} != event:
                result = api_send('PUT', f'{base}/{schedule["type"]}/{match["id"]}/events/{cur["id"]}',
                                  headers, logger, event)
                action = 'Updated'
            else:
                continue
            if result is None:
                failed += 1
            else:
                changes += 1
                logger.info(f'[{t["name"]}] {action} event "{event.get("name")}".')
        if changes:
            updated += 1
        else:
            logger.info(f'[{t["name"]}] "{schedule["name"]}" already up to date.')
            unchanged += 1

    logger.info(f'Done: {created} created, {updated} updated, {unchanged} unchanged, {failed} failed.')
    logger.info(f'{TITLE} - Completed')


if __name__ == '__main__':
    main()
