#!/usr/bin/env python3
# TITLE: User Workspace Migration Location

"""
Migrate the owner of a phone number to a new Webex Calling location.

Offers to read the numbers from a CSV (default _DATA/migration_userWorkspace_location.csv)
or to enter a single number. Then asks for the new location (search text, numbered
list if more than one matches).

For each number the owner is looked up. Only numbers that are the PRIMARY number of a
user (PEOPLE) or a workspace (PLACE) are acted on. Everything else (alternate numbers,
hunt groups, call queues, auto attendants, virtual lines, unassigned or unknown numbers,
owners already at the target location) is skipped and logged.

  * User: validated, then moved with the Move Users job. The user keeps the existing
    phone number and extension. Validation errors cause the user to be skipped and
    impacts are logged. The job is polled until it completes.
  * Workspace: the public Webex API cannot change a workspace location (locationId
    cannot be changed once configured), so workspaces are logged as skipped and must
    be recreated or moved in Control Hub.

A summary is shown and confirmation is requested before any user is moved.

Input CSV columns (see _DATA/examples/migration_userWorkspace_location.csv.EXAMPLE):
    number   (E.164 such as +14155551234, or a 10 digit US number)

Uses the Calling admin API (spark-admin:telephony_config_read / _write,
spark-admin:people_write, identity:groups_rw):
    GET  /v1/telephony/config/numbers?phoneNumber=
    POST /v1/telephony/config/jobs/person/moveLocation  (validate true, then false)
    GET  /v1/telephony/config/jobs/person/moveLocation/{jobId}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Logs: ../_logs/<timestamp>-migration_userWorkspace_location.log
"""

import warnings
warnings.simplefilter('ignore')

import csv
import os
import re
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from export_location_holidaySchedule import (API_BASE, get_token, api_get,
                                             select_from_list, find_locations)
from update_location_holidayschedule import api_send

TITLE = 'User Workspace Migration Location'
NUMBERS_URL = f'{API_BASE}/telephony/config/numbers'
MOVE_URL = f'{API_BASE}/telephony/config/jobs/person/moveLocation'
DEFAULT_CSV = os.path.join(BASE_DIR, '_DATA', 'migration_userWorkspace_location.csv')
JOB_TIMEOUT_SECONDS = 180
JOB_POLL_SECONDS = 5


def normalize_number(raw):
    """Return the number in E.164 form (assumes US/Canada for 10 and 11 digit input)."""
    raw = (raw or '').strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    if raw.startswith('+'):
        return f'+{digits}'
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    return f'+{digits}'


def load_numbers(path, logger):
    """Read the number column from the CSV; header row is skipped, extra columns ignored."""
    numbers = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return numbers
        col = 0
        for i, name in enumerate(header):
            if name.strip().lower() == 'number':
                col = i
                break
        else:
            logger.warning('No "number" column header found; using the first column.')
        for row in reader:
            if len(row) > col and row[col].strip():
                number = normalize_number(row[col])
                if number and number not in numbers:
                    numbers.append(number)
    return numbers


def choose_location(headers, logger):
    while True:
        search = input('Enter text to search for the new location: ').strip()
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
            return select_from_list(matches, lambda loc: loc.get('name', ''), 'location')


def lookup_number(number, headers, logger):
    """Return the numbers API record for an exact number match, or None."""
    data = api_get(NUMBERS_URL, headers, logger, params={'phoneNumber': number})
    if data is None:
        return None
    for item in data.get('phoneNumbers', []):
        if item.get('phoneNumber') == number:
            return item
    return {}


def classify(number, record, location):
    """Return (action, reason). action is 'user', 'workspace' or 'skip'."""
    if record is None:
        return 'skip', 'lookup failed'
    if not record:
        return 'skip', 'number not found'
    owner = record.get('owner') or {}
    owner_type = owner.get('type')
    if not owner.get('id'):
        return 'skip', f'number is {record.get("state", "unassigned")} with no owner'
    if owner_type not in ('PEOPLE', 'PLACE'):
        return 'skip', f'owner type is {owner_type}'
    if record.get('phoneNumberType') != 'PRIMARY':
        return 'skip', f'not the primary number ({record.get("phoneNumberType")})'
    if (record.get('location') or {}).get('id') == location['id']:
        return 'skip', 'owner is already at the target location'
    return ('user' if owner_type == 'PEOPLE' else 'workspace'), ''


def owner_name(owner):
    return f'{owner.get("firstName", "")} {owner.get("lastName", "")}'.strip() or owner.get('id', '')


def move_body(user_id, location_id, validate):
    return {'usersList': [{'locationId': location_id, 'validate': validate,
                           'users': [{'userId': user_id}]}]}


def validate_move(user_id, location_id, headers, logger):
    """Validate a move; return True when there are no errors."""
    result = api_send('POST', MOVE_URL, headers, logger, move_body(user_id, location_id, True))
    if result is None:
        return False
    users = (result.get('response', result)).get('usersList', [])
    ok = True
    for item in users:
        for impact in item.get('impacts') or []:
            logger.warning(f'  Impact {impact.get("code")}: {impact.get("message")}')
        for error in item.get('errors') or []:
            logger.error(f'  Error {error.get("code")}: {error.get("message")}')
            ok = False
    return ok


def run_move(user_id, location_id, headers, logger):
    """Start the move job and wait for it to finish; return True on COMPLETED."""
    result = api_send('POST', MOVE_URL, headers, logger, move_body(user_id, location_id, False))
    if result is None:
        return False
    body = result.get('response', result)
    users = body.get('usersList', [])
    for item in users:
        for error in item.get('errors') or []:
            logger.error(f'  Error {error.get("code")}: {error.get("message")}')
    if any(item.get('errors') for item in users):
        return False
    job_id = (body.get('jobDetails') or {}).get('id')
    if not job_id:
        logger.error('  Move job id was not returned.')
        return False
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    status = ''
    while time.time() < deadline:
        job = api_get(f'{MOVE_URL}/{job_id}', headers, logger)
        if job is None:
            return False
        status = job.get('latestExecutionStatus', '')
        if status in ('COMPLETED', 'FAILED'):
            counts = job.get('counts') or {}
            logger.info(f'  Move job {job_id} {status} {counts}')
            if status == 'COMPLETED' and not counts.get('usersFailed'):
                return True
            return False
        time.sleep(JOB_POLL_SECONDS)
    logger.error(f'  Move job {job_id} still {status or "pending"} after {JOB_TIMEOUT_SECONDS}s. '
                 f'Check Control Hub.')
    return False


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-migration_userWorkspace_location.log'
    logger = setup_logger(log_file)
    logger.info(f'{TITLE} - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json',
               'Content-Type': 'application/json'}

    # Numbers
    numbers = []
    if prompt_yes_no('Read the numbers from a CSV file?', default=True):
        csv_path = input(f'Path to CSV [{DEFAULT_CSV}]: ').strip() or DEFAULT_CSV
        if not os.path.isfile(csv_path):
            logger.error(f'CSV not found: {csv_path}')
            logger.info(f'{TITLE} - Completed')
            return
        numbers = load_numbers(csv_path, logger)
    else:
        number = normalize_number(input('Enter the phone number: '))
        if number:
            numbers = [number]
    if not numbers:
        logger.error('No numbers to process.')
        logger.info(f'{TITLE} - Completed')
        return
    logger.info(f'{len(numbers)} number(s) to process.')

    # New location
    location = choose_location(headers, logger)
    if location is None:
        logger.info(f'{TITLE} - Completed')
        return
    logger.info(f'New location: {location["name"]}')

    # Lookup and classify
    plan = []
    skipped = 0
    for number in numbers:
        record = lookup_number(number, headers, logger)
        action, reason = classify(number, record, location)
        owner = (record or {}).get('owner') or {}
        if action == 'skip':
            logger.warning(f'Skipped {number}: {reason}')
            skipped += 1
        elif action == 'workspace':
            logger.warning(f'Skipped {number}: workspace {owner_name(owner)} cannot be moved by API; '
                           f'use Control Hub')
            skipped += 1
        else:
            plan.append((number, owner))

    if not plan:
        logger.info(f'Nothing to migrate. Skipped: {skipped}')
        logger.info(f'{TITLE} - Completed')
        return

    print(f'\nUsers to move to "{location["name"]}":')
    for number, owner in plan:
        print(f'  {number}  {owner_name(owner)}')
    if not prompt_yes_no(f'Validate and move {len(plan)} user(s)?', default=False):
        logger.info('Migration declined by user.')
        logger.info(f'{TITLE} - Completed')
        return

    moved = failed = 0
    for number, owner in plan:
        name = owner_name(owner)
        logger.info(f'Validating {number} {name}')
        if not validate_move(owner['id'], location['id'], headers, logger):
            logger.error(f'Skipped {number} {name}: validation failed')
            failed += 1
            continue
        logger.info(f'Moving {number} {name}')
        if run_move(owner['id'], location['id'], headers, logger):
            logger.info(f'Moved {number} {name} to {location["name"]}')
            moved += 1
        else:
            logger.error(f'Move failed for {number} {name}')
            failed += 1

    logger.info(f'Moved: {moved}  Failed: {failed}  Skipped: {skipped}')
    logger.info(f'{TITLE} - Completed')


if __name__ == '__main__':
    main()
