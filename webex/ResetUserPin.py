#!/usr/bin/env python3
# TITLE: User PIN Reset

"""
Reset the voicemail PIN for Webex Calling users listed in a CSV.

Each email is looked up; users without a Webex Calling license are skipped.
A summary count is shown and confirmation is requested before any PIN is reset.

Uses the Webex APIs:
    GET  /v1/people?email=
    GET  /v1/licenses
    POST /v1/people/{personId}/features/voicemail/actions/resetPin/invoke

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Input CSV columns (see _DATA/examples/reset_user_pin.csv.EXAMPLE):
    Email
    Header row is skipped. Extra columns are ignored.

Logs: ../_logs/<timestamp>-ResetUserPin.log
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
from export_location_holidaySchedule import get_token, api_get

API_BASE = 'https://webexapis.com/v1'
DEFAULT_CSV = os.path.join(BASE_DIR, '_DATA', 'reset_user_pin.csv')
CALLING_LICENSE_NAME = 'Webex Calling - Professional'


def load_emails(path):
    """Return the first column of each CSV row after the header."""
    emails = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = csv.reader(f)
        next(rows, None)
        for row in rows:
            if row and row[0].strip():
                emails.append(row[0].strip())
    return emails


def get_calling_license_ids(headers, logger):
    """Return the IDs of all Webex Calling licenses."""
    data = api_get(f'{API_BASE}/licenses', headers, logger)
    if not data:
        return []
    return [lic['id'] for lic in data.get('items', []) if lic.get('name') == CALLING_LICENSE_NAME]


def lookup_user(email, license_ids, headers, logger):
    """Return the person ID of a user with a Calling license, or None."""
    data = api_get(f'{API_BASE}/people', headers, logger, params={'email': email})
    if data is None:
        return None
    for user in data.get('items', []):
        if any(lic in license_ids for lic in user.get('licenses', [])):
            return user['id']
    logger.warning(f'Skipping {email}: invalid user or no Calling license.')
    return None


def reset_pin(person_id, headers, logger):
    """Reset the voicemail PIN; return True on success."""
    url = f'{API_BASE}/people/{person_id}/features/voicemail/actions/resetPin/invoke'
    response = requests.post(url, headers=headers, timeout=30)
    if response.status_code != 204:
        logger.error(f'POST {url} failed: HTTP {response.status_code} {response.text}')
        return False
    return True


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-ResetUserPin.log'
    logger = setup_logger(log_file)
    logger.info('Reset User PIN - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    csv_path = input(f'Path to user CSV [{DEFAULT_CSV}]: ').strip() or DEFAULT_CSV
    if not os.path.isfile(csv_path):
        logger.error(f'CSV not found: {csv_path}')
        logger.info('Reset User PIN - Completed')
        return
    emails = load_emails(csv_path)
    if not emails:
        logger.warning('No users found in the CSV.')
        logger.info('Reset User PIN - Completed')
        return

    license_ids = get_calling_license_ids(headers, logger)
    if not license_ids:
        logger.error(f'No "{CALLING_LICENSE_NAME}" licenses found.')
        logger.info('Reset User PIN - Completed')
        return

    targets = []
    for email in emails:
        person_id = lookup_user(email, license_ids, headers, logger)
        if person_id:
            targets.append((email, person_id))

    print(f'\n{len(targets)} of {len(emails)} user(s) eligible for PIN reset.')
    if not targets:
        logger.info('Reset User PIN - Completed')
        return
    if not prompt_yes_no('Reset PINs for these users?', default=False):
        logger.info('Reset declined by user.')
        logger.info('Reset User PIN - Completed')
        return

    ok = failed = 0
    for email, person_id in targets:
        if reset_pin(person_id, headers, logger):
            logger.info(f'{email} PIN reset.')
            ok += 1
        else:
            failed += 1
    logger.info(f'Done: {ok} succeeded, {failed} failed.')
    logger.info('Reset User PIN - Completed')


if __name__ == '__main__':
    main()
