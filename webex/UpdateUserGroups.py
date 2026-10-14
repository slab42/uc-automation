#!/usr/bin/env python3
# TITLE: User Groups Update

"""
Add users to, or remove users from, a Webex group using a CSV of email addresses.

Prompts for the CSV path (default _DATA/user_groups.csv), the group (numbered
list) and whether to Add or Remove the listed users. Only the listed users are
changed; existing group members are left alone. Emails that do not match a
Webex user are logged and skipped.

Uses the Webex REST API:
    GET   /v1/groups
    GET   /v1/people?email=
    PATCH /v1/groups/{groupId}   (members with operation add|delete)

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Input CSV columns (see _DATA/examples/user_groups.csv.EXAMPLE):
    Email
    The first column of each row is used; the header row is skipped.

Logs: ../_logs/<timestamp>-UpdateUserGroups.log
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
from export_location_holidaySchedule import API_BASE, get_token, api_get, select_from_list

GROUPS_URL = f'{API_BASE}/groups'
PEOPLE_URL = f'{API_BASE}/people'
DEFAULT_CSV = os.path.join(BASE_DIR, '_DATA', 'user_groups.csv')


def read_emails(path):
    """Return the email addresses from the first column of the CSV (header skipped)."""
    emails = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows = csv.reader(f)
        next(rows, None)
        for row in rows:
            if row and row[0].strip():
                emails.append(row[0].strip())
    return emails


def lookup_user(email, headers, logger):
    """Return the Webex person ID for an email, or None if not found."""
    data = api_get(PEOPLE_URL, headers, logger, params={'email': email})
    if data is None:
        return None
    items = data.get('items', [])
    if not items:
        logger.error(f'Skipping {email} - no matching Webex user.')
        return None
    return items[0]['id']


def list_groups(headers, logger):
    """Return all groups, following pagination."""
    groups = []
    url, params = GROUPS_URL, {'max': 100}
    while url:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            logger.error(f'GET {url} failed: HTTP {response.status_code} {response.text}')
            return groups
        groups.extend(response.json().get('groups', []))
        url = response.links.get('next', {}).get('url')
        params = None
    return groups


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-UpdateUserGroups.log'
    logger = setup_logger(log_file)
    logger.info('Update User Groups - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    # Input CSV
    csv_path = input(f'Enter CSV file path [{DEFAULT_CSV}]: ').strip() or DEFAULT_CSV
    try:
        emails = read_emails(os.path.expanduser(csv_path))
    except OSError as e:
        logger.error(f'Unable to read {csv_path}: {e}')
        return
    if not emails:
        logger.error(f'No email addresses found in {csv_path}.')
        return
    logger.info(f'Read {len(emails)} email(s) from {csv_path}.')

    # Group selection
    groups = list_groups(headers, logger)
    if not groups:
        logger.error('No groups found.')
        return
    group = select_from_list(groups, lambda g: g.get('displayName', g['id']), 'group')
    logger.info(f'Group selected: {group.get("displayName")}')

    # Add or remove
    while True:
        choice = input('Add or Remove these users? [A]dd, [R]emove [A]: ').strip().lower() or 'a'
        if choice in ('a', 'r'):
            break
        print('Invalid selection.')
    operation, past = ('add', 'added') if choice == 'a' else ('delete', 'removed')

    # Resolve users
    members = []
    for email in emails:
        logger.info(f'Processing {email}...')
        user_id = lookup_user(email, headers, logger)
        if user_id:
            members.append({'id': user_id, 'operation': operation})

    if not members:
        logger.error('No valid users to update.')
        logger.info('Update User Groups - Completed')
        return

    # Update the group
    response = requests.patch(f'{GROUPS_URL}/{group["id"]}',
                              headers={**headers, 'Content-Type': 'application/json'},
                              json={'members': members}, timeout=30)
    if response.status_code in (200, 201, 202, 204):
        logger.info(f'Group updated: {len(members)} user(s) {past}, '
                    f'{len(emails) - len(members)} skipped.')
    else:
        logger.error(f'Group update failed: HTTP {response.status_code} {response.text}')

    logger.info('Update User Groups - Completed')


if __name__ == '__main__':
    main()
