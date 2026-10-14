#!/usr/bin/env python3
# TITLE: Location Holiday Schedule Update

"""
Add or update a Webex Calling location holiday schedule from CSV.

Prompts for text to search for the location. If more than one location
matches, a numbered list is offered. The CSV (default _DATA/holiday_schedule.csv)
is then read and each distinct schedule Name is processed:
  - If a holiday schedule with that name exists at the location, events are
    added to / removed from it.
  - If it does not exist, it is created (ADD rows only; REMOVE rows are skipped).
A summary is shown and confirmation is requested before any change is made.

Uses the Calling admin API (spark-admin:telephony_config_read / _write):
    GET    /v1/telephony/config/locations
    GET    /v1/telephony/config/locations/{locationId}/schedules
    GET    /v1/telephony/config/locations/{locationId}/schedules/holidays/{scheduleId}
    POST   /v1/telephony/config/locations/{locationId}/schedules
    POST   /v1/telephony/config/locations/{locationId}/schedules/holidays/{scheduleId}/events
    DELETE /v1/telephony/config/locations/{locationId}/schedules/holidays/{scheduleId}/events/{eventId}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Input CSV columns (see _DATA/examples/holiday_schedule.csv.EXAMPLE):
    Name,Event action,Event name,Event start date,Event end date
    Event action is ADD or REMOVE. Dates are M/D/YY (or YYYY-MM-DD).
    ADD rows whose event name already exists in the schedule are skipped.
    REMOVE rows match the existing event by name (case-insensitive).
    Blank rows are ignored. Events are created as all-day events.

Logs: ../_logs/<timestamp>-update_location_holidayschedule.log
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
from export_location_holidaySchedule import (
    LOCATIONS_URL, get_token, api_get, select_from_list, find_locations,
)

DEFAULT_CSV = os.path.join(BASE_DIR, '_DATA', 'holiday_schedule.csv')
SCHEDULE_TYPE = 'holidays'


def parse_date(value):
    """Convert M/D/YY, M/D/YYYY or YYYY-MM-DD to YYYY-MM-DD; None if invalid."""
    value = (value or '').strip()
    for fmt in ('%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def load_csv(path, logger):
    """Return {schedule name: [rows]} preserving CSV order; invalid rows are logged and skipped."""
    schedules = {}
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, 2):
            name = (row.get('Name') or '').strip()
            action = (row.get('Event action') or '').strip().upper()
            event = (row.get('Event name') or '').strip()
            if not (name or action or event):
                continue
            start = parse_date(row.get('Event start date'))
            end = parse_date(row.get('Event end date')) or start
            if not name or not event or action not in ('ADD', 'REMOVE') or not start:
                logger.warning(f'Line {line_no}: invalid row skipped: {dict(row)}')
                continue
            schedules.setdefault(name, []).append(
                {'action': action, 'name': event, 'start': start, 'end': end})
    return schedules


def build_plan(schedules, existing, location, headers, logger):
    """Work out the changes per schedule. Returns a list of plan dicts."""
    by_name = {s['name'].lower(): s for s in existing if s.get('type') == SCHEDULE_TYPE}
    plan = []
    for name, rows in schedules.items():
        sched = by_name.get(name.lower())
        events = []
        if sched:
            detail = api_get(f'{LOCATIONS_URL}/{location["id"]}/schedules/{SCHEDULE_TYPE}/{sched["id"]}',
                             headers, logger)
            if detail is None:
                logger.error(f'Unable to read schedule "{name}"; skipping.')
                continue
            events = detail.get('events', [])
        current = {e.get('name', '').lower(): e for e in events}

        adds, removes = [], []
        for r in rows:
            key = r['name'].lower()
            if r['action'] == 'ADD':
                if key in current:
                    logger.info(f'  [{name}] "{r["name"]}" already exists; skipped.')
                else:
                    adds.append(r)
                    current[key] = {}  # guard against duplicate ADD rows
            elif not sched:
                logger.warning(f'  [{name}] REMOVE "{r["name"]}" skipped: schedule does not exist.')
            elif key in current and current[key].get('id'):
                removes.append(current[key])
            else:
                logger.warning(f'  [{name}] REMOVE "{r["name"]}" skipped: event not found.')
        plan.append({'name': name, 'schedule': sched, 'adds': adds, 'removes': removes})
    return plan


def event_body(r):
    return {'name': r['name'], 'startDate': r['start'], 'endDate': r['end'], 'allDayEnabled': True}


def api_send(method, url, headers, logger, body=None):
    """POST/DELETE a URL; return parsed JSON ({} when empty) or None on error."""
    response = requests.request(method, url, headers=headers, json=body, timeout=30)
    if response.status_code not in (200, 201, 204):
        logger.error(f'{method} {url} failed: HTTP {response.status_code} {response.text}')
        return None
    return response.json() if response.content else {}


def apply_plan(plan, location, headers, logger):
    base = f'{LOCATIONS_URL}/{location["id"]}/schedules'
    ok = failed = 0
    for item in plan:
        name = item['name']
        sched = item['schedule']
        adds = item['adds']
        if not sched:
            if not adds:
                continue
            body = {'type': SCHEDULE_TYPE, 'name': name, 'events': [event_body(r) for r in adds]}
            result = api_send('POST', base, headers, logger, body)
            if result is None:
                failed += len(adds)
            else:
                ok += len(adds)
                logger.info(f'Created schedule "{name}" with {len(adds)} event(s).')
            continue
        for r in adds:
            result = api_send('POST', f'{base}/{SCHEDULE_TYPE}/{sched["id"]}/events',
                              headers, logger, event_body(r))
            if result is None:
                failed += 1
            else:
                ok += 1
                logger.info(f'  [{name}] Added "{r["name"]}" ({r["start"]} to {r["end"]}).')
        for e in item['removes']:
            result = api_send('DELETE', f'{base}/{SCHEDULE_TYPE}/{sched["id"]}/events/{e["id"]}',
                              headers, logger)
            if result is None:
                failed += 1
            else:
                ok += 1
                logger.info(f'  [{name}] Removed "{e.get("name")}".')
    return ok, failed


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-update_location_holidayschedule.log'
    logger = setup_logger(log_file)
    logger.info('Update Location Holiday Schedule - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json',
               'Content-Type': 'application/json'}

    # Find the target location
    location = None
    while location is None:
        search = input('Enter text to search for the location: ').strip()
        if not search:
            continue
        matches = find_locations(headers, search, logger)
        if not matches:
            logger.warning(f'No locations match "{search}".')
            if not prompt_yes_no('Search again?', default=True):
                logger.info('Update Location Holiday Schedule - Completed')
                return
        elif len(matches) == 1:
            location = matches[0]
        else:
            location = select_from_list(matches, lambda l: l['name'], 'location')
    logger.info(f'Location: {location["name"]}')

    # Load the CSV
    csv_path = input(f'Path to holiday schedule CSV [{DEFAULT_CSV}]: ').strip() or DEFAULT_CSV
    if not os.path.isfile(csv_path):
        logger.error(f'CSV not found: {csv_path}')
        logger.info('Update Location Holiday Schedule - Completed')
        return
    schedules = load_csv(csv_path, logger)
    if not schedules:
        logger.warning('No valid rows found in the CSV.')
        logger.info('Update Location Holiday Schedule - Completed')
        return

    # Compare against what exists at the location
    data = api_get(f'{LOCATIONS_URL}/{location["id"]}/schedules', headers, logger)
    if data is None:
        logger.info('Update Location Holiday Schedule - Completed')
        return
    plan = build_plan(schedules, data.get('schedules', []), location, headers, logger)

    print(f'\nPlanned changes for {location["name"]}:')
    for item in plan:
        state = 'update existing' if item['schedule'] else 'create new'
        print(f'  {item["name"]} ({state}): add {len(item["adds"])}, remove {len(item["removes"])}')
    if not any(i['adds'] or i['removes'] for i in plan):
        logger.info('Nothing to change.')
        logger.info('Update Location Holiday Schedule - Completed')
        return

    if not prompt_yes_no('Apply these changes?', default=False):
        logger.info('Changes declined by user.')
        logger.info('Update Location Holiday Schedule - Completed')
        return

    ok, failed = apply_plan(plan, location, headers, logger)
    logger.info(f'Done: {ok} succeeded, {failed} failed.')
    logger.info('Update Location Holiday Schedule - Completed')


if __name__ == '__main__':
    main()
