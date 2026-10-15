#!/usr/bin/env python3
# TITLE: Virtual Line Upload Busy Greeting

"""
Upload a custom busy and unanswered voicemail greeting to a Webex Calling Virtual Line.

Prompts for text to search for the Virtual Line (matches name, extension or
phone number). If more than one Virtual Line matches, a numbered list is
offered. Next, prompts for the greeting file name. The file must be a .wav
file of 5000 KB or less. A bare file name is looked for in the current
directory first, then in the repo _DATA folder. A summary is shown and
confirmation is requested before the upload. The same file is uploaded as both
the busy and the unanswered (no answer) greeting. After each successful upload
that greeting is set to CUSTOM (the enabled settings and the number of rings
are left as they are).

Uses the Calling admin API (spark-admin:telephony_config_read / _write):
    GET  /v1/telephony/config/virtualLines
    POST /v1/telephony/config/virtualLines/{virtualLineId}/voicemail/actions/uploadBusyGreeting/invoke
         (multipart/form-data, field "file", audio/wav)
    POST /v1/telephony/config/virtualLines/{virtualLineId}/voicemail/actions/uploadNoAnswerGreeting/invoke
    GET  /v1/telephony/config/virtualLines/{virtualLineId}/voicemail
    PUT  /v1/telephony/config/virtualLines/{virtualLineId}/voicemail
         (sendBusyCalls.greeting and sendUnansweredCalls.greeting = CUSTOM)

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Logs: ../_logs/<timestamp>-virtualLine_busyGreeting.log
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
from export_location_holidaySchedule import API_BASE, get_token, api_get, select_from_list

TITLE = 'Virtual Line Upload Busy Greeting'
VIRTUAL_LINES_URL = f'{API_BASE}/telephony/config/virtualLines'
MAX_GREETING_KB = 5000


def line_label(line):
    name = line.get('displayName') or f'{line.get("firstName", "")} {line.get("lastName", "")}'.strip()
    number = line.get('number') or {}
    digits = number.get('external') or number.get('extension') or ''
    location = (line.get('location') or {}).get('name', '')
    return f'{name} | {digits} | {location}'.strip()


def find_virtual_lines(headers, search, logger):
    """Return all virtual lines whose name, extension or number contains the search text."""
    lines = []
    start = 0
    while True:
        data = api_get(VIRTUAL_LINES_URL, headers, logger, params={'max': 100, 'start': start})
        if not data:
            break
        page = data.get('virtualLines', [])
        lines.extend(page)
        if len(page) < 100:
            break
        start += 100
    text = search.lower()
    return [l for l in lines if text in line_label(l).lower()
            or text in ((l.get('number') or {}).get('extension') or '').lower()]


def choose_virtual_line(headers, logger):
    while True:
        search = input('Enter text to search for the Virtual Line: ').strip()
        if not search:
            continue
        matches = find_virtual_lines(headers, search, logger)
        if not matches:
            logger.warning(f'No virtual lines match "{search}".')
            if not prompt_yes_no('Search again?', default=True):
                return None
        elif len(matches) == 1:
            return matches[0]
        else:
            return select_from_list(matches, line_label, 'virtual line')


def resolve_greeting(name):
    """Return the full path of the greeting file, or None if it cannot be found."""
    name = os.path.expanduser(name.strip().strip('"').strip("'"))
    for candidate in (name, os.path.join(BASE_DIR, '_DATA', name)):
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def choose_greeting(logger):
    while True:
        name = input('Enter the greeting file name (.wav): ').strip()
        if not name:
            continue
        path = resolve_greeting(name)
        if path is None:
            logger.warning(f'File not found: {name}')
        elif not path.lower().endswith('.wav'):
            logger.warning('Greeting must be a .wav file.')
        elif os.path.getsize(path) > MAX_GREETING_KB * 1024:
            logger.warning(f'Greeting exceeds {MAX_GREETING_KB} KB.')
        else:
            return path
        if not prompt_yes_no('Try another file?', default=True):
            return None


def upload_greeting(line, path, token, logger, action):
    """Upload the file; action is 'uploadBusyGreeting' or 'uploadNoAnswerGreeting'."""
    url = f'{VIRTUAL_LINES_URL}/{line["id"]}/voicemail/actions/{action}/invoke'
    with open(path, 'rb') as f:
        response = requests.post(
            url, headers={'Authorization': f'Bearer {token}'},
            files={'file': (os.path.basename(path), f, 'audio/wav')}, timeout=60)
    if response.status_code not in (200, 201, 204):
        logger.error(f'POST {url} failed: HTTP {response.status_code} {response.text}')
        return False
    return True


def set_custom_greeting(line, headers, logger, setting):
    """Set the busy or unanswered greeting (setting = 'sendBusyCalls' / 'sendUnansweredCalls') to CUSTOM,
    keeping its current enabled value (and number of rings for unanswered calls)."""
    url = f'{VIRTUAL_LINES_URL}/{line["id"]}/voicemail'
    current = api_get(url, headers, logger)
    if current is None:
        return False
    existing = current.get(setting) or {}
    section = {'enabled': existing.get('enabled', False), 'greeting': 'CUSTOM'}
    if setting == 'sendUnansweredCalls' and 'numberOfRings' in existing:
        section['numberOfRings'] = existing['numberOfRings']
    response = requests.put(url, headers={**headers, 'Content-Type': 'application/json'},
                            json={setting: section}, timeout=30)
    if response.status_code not in (200, 204):
        logger.error(f'PUT {url} failed: HTTP {response.status_code} {response.text}')
        return False
    return True


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-virtualLine_busyGreeting.log'
    logger = setup_logger(log_file)
    logger.info(f'{TITLE} - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    line = choose_virtual_line(headers, logger)
    if line is None:
        logger.info(f'{TITLE} - Completed')
        return
    logger.info(f'Selected virtual line: {line_label(line)}')

    path = choose_greeting(logger)
    if path is None:
        logger.info(f'{TITLE} - Completed')
        return

    print(f'\nUpload "{os.path.basename(path)}" as the busy and unanswered greeting for: {line_label(line)}')
    if not prompt_yes_no('Apply this change?', default=False):
        logger.info('Upload declined by user.')
        logger.info(f'{TITLE} - Completed')
        return

    name = os.path.basename(path)
    for label, action, setting in (('busy', 'uploadBusyGreeting', 'sendBusyCalls'),
                                   ('unanswered', 'uploadNoAnswerGreeting', 'sendUnansweredCalls')):
        if not upload_greeting(line, path, token, logger, action):
            continue
        logger.info(f'{label.capitalize()} greeting "{name}" uploaded to {line_label(line)}.')
        if set_custom_greeting(line, headers, logger, setting):
            logger.info(f'{label.capitalize()} greeting set to CUSTOM.')
        else:
            logger.error(f'{label.capitalize()} greeting uploaded, but setting it to CUSTOM failed. '
                         'Set it in Control Hub.')
    logger.info(f'{TITLE} - Completed')


if __name__ == '__main__':
    main()
