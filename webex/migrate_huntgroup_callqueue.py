#!/usr/bin/env python3
# TITLE: Call Queue Migrate Hunt Group

"""
Migrate a Webex Calling Hunt Group to a Call Queue.

Prompts for text to search for a hunt group. If more than one matches, a numbered
list is offered. The hunt group settings are read in and saved to a JSON backup,
a summary is shown and confirmation is requested. Then:
  1. The hunt group is deleted (this frees its name, phone number and extension).
  2. A Call Queue is created at the same location using the hunt group settings
     (name, number, extension, name fields, language, time zone, enabled, routing
     policy, no-answer rings as call bounce, distinctive ring).
  3. The hunt group agents are added to the queue and set as joined.

Settings with no direct Call Queue equivalent (forwarding on no answer, busy
redirect, business continuity, alternate numbers) are logged but not migrated.
Queue size (10) and overflow (busy treatment) use defaults.

Uses the Calling admin API (spark-admin:telephony_config_read / _write):
    GET    /v1/telephony/config/huntGroups
    GET    /v1/telephony/config/locations/{locationId}/huntGroups/{huntGroupId}
    DELETE /v1/telephony/config/locations/{locationId}/huntGroups/{huntGroupId}
    POST   /v1/telephony/config/locations/{locationId}/queues
    GET    /v1/telephony/config/locations/{locationId}/queues/{queueId}
    PUT    /v1/telephony/config/locations/{locationId}/queues/{queueId}

Credentials: Webex api_token from [WEBEX:default] in .env/credentials.env.
If not stored, the token is requested at runtime (input is hidden).

Output: _logs/<timestamp>-hunt_group_backup-<name>.json (original hunt group settings)
Logs: ../_logs/<timestamp>-migrate_huntgroup_callqueue.log
"""

import warnings
warnings.simplefilter('ignore')

import json
import os
import sys
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from export_location_holidaySchedule import API_BASE, get_token, api_get, select_from_list, safe_name
from update_location_holidayschedule import api_send

TITLE = 'Call Queue Migrate Hunt Group'
HUNT_GROUPS_URL = f'{API_BASE}/telephony/config/huntGroups'
LOCATIONS_URL = f'{API_BASE}/telephony/config/locations'

# Hunt group settings with no Call Queue create equivalent
UNMAPPED = ('noAnswer destination/forwarding', 'busyRedirect', 'businessContinuityRedirect',
            'alternateNumberSettings')


def find_hunt_groups(headers, search, logger):
    """Return all hunt groups whose name contains the search text."""
    groups = []
    start = 0
    while True:
        data = api_get(HUNT_GROUPS_URL, headers, logger,
                       params={'name': search, 'max': 100, 'start': start})
        if not data:
            break
        page = data.get('huntGroups', [])
        groups.extend(page)
        if len(page) < 100:
            break
        start += 100
    return [g for g in groups if search.lower() in g.get('name', '').lower()]


def choose_hunt_group(headers, logger):
    while True:
        search = input('Enter text to search for a hunt group: ').strip()
        if not search:
            continue
        matches = find_hunt_groups(headers, search, logger)
        if not matches:
            logger.warning(f'No hunt groups match "{search}".')
            if not prompt_yes_no('Search again?', default=True):
                return None
        elif len(matches) == 1:
            return matches[0]
        else:
            return select_from_list(
                matches, lambda g: f'{g["name"]} ({g.get("locationName", "")}) '
                                   f'{g.get("extension", "")} {g.get("phoneNumber", "")}'.rstrip(),
                'hunt group')


def build_queue_body(hg):
    """Map hunt group settings to a Call Queue create body."""
    policies = hg.get('callPolicies', {})
    no_answer = policies.get('noAnswer', {})
    call_policies = {
        'routingType': 'PRIORITY_BASED',
        'policy': policies.get('policy', 'CIRCULAR'),
        'callBounce': {
            'callBounceEnabled': bool(no_answer.get('nextAgentEnabled', False)),
            'callBounceMaxRings': no_answer.get('nextAgentRings', 3),
        },
    }
    if hg.get('distinctiveRing'):
        call_policies['distinctiveRing'] = hg['distinctiveRing']

    body = {
        'name': hg['name'],
        'callPolicies': call_policies,
        'queueSettings': {
            'queueSize': 10,
            'overflow': {'action': 'PERFORM_BUSY_TREATMENT'},
        },
        'allowAgentJoinEnabled': True,
        'phoneNumberForOutgoingCallsEnabled': True,
        'agents': [{'id': a['id']} for a in hg.get('agents', [])],
    }
    for key in ('phoneNumber', 'extension', 'firstName', 'lastName', 'languageCode',
                'timeZone', 'enabled'):
        if hg.get(key) not in (None, ''):
            body[key] = hg[key]
    return body


def log_unmapped(hg, logger):
    policies = hg.get('callPolicies', {})
    no_answer = policies.get('noAnswer', {})
    if no_answer.get('forwardEnabled'):
        logger.warning(f'Not migrated: no-answer forward after {no_answer.get("numberOfRings")} rings '
                       f'to {no_answer.get("destination")}')
    for key in ('busyRedirect', 'businessContinuityRedirect'):
        if policies.get(key, {}).get('enabled'):
            logger.warning(f'Not migrated: {key} {json.dumps(policies[key])}')
    if hg.get('alternateNumberSettings', {}).get('alternateNumbers'):
        logger.warning(f'Not migrated: alternate numbers {json.dumps(hg["alternateNumberSettings"])}')


def join_agents(location_id, queue_id, headers, logger):
    """Make sure every agent on the new queue is joined."""
    url = f'{LOCATIONS_URL}/{location_id}/queues/{queue_id}'
    queue = api_get(url, headers, logger)
    if queue is None:
        return False
    agents = queue.get('agents', [])
    if agents and all(a.get('joinEnabled') for a in agents):
        logger.info(f'All {len(agents)} agent(s) are joined.')
        return True
    body = {'agents': [{'id': a['id'], 'joinEnabled': True} for a in agents]}
    if api_send('PUT', url, headers, logger, body) is None:
        return False
    logger.info(f'Set {len(agents)} agent(s) as joined.')
    return True


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = f'../_logs/{timestamp}-migrate_huntgroup_callqueue.log'
    logger = setup_logger(log_file)
    logger.info(f'{TITLE} - Started')

    token = get_token(logger)
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json',
               'Content-Type': 'application/json'}

    summary = choose_hunt_group(headers, logger)
    if summary is None:
        logger.info(f'{TITLE} - Completed')
        return
    location_id = summary['locationId']
    hg_url = f'{LOCATIONS_URL}/{location_id}/huntGroups/{summary["id"]}'

    # Read hunt group settings
    hg = api_get(hg_url, headers, logger)
    if hg is None:
        logger.error('Unable to read hunt group settings.')
        logger.info(f'{TITLE} - Completed')
        return
    hg.setdefault('name', summary['name'])
    agents = hg.get('agents', [])
    logger.info(f'Hunt group: {hg["name"]} at {summary.get("locationName", location_id)}, '
                f'{len(agents)} agent(s)')

    os.makedirs('../_logs', exist_ok=True)
    backup = f'../_logs/{timestamp}-hunt_group_backup-{safe_name(hg["name"])}.json'
    with open(backup, 'w', encoding='utf8') as f:
        json.dump(hg, f, indent=2)
    logger.info(f'Hunt group settings saved to {backup}')

    body = build_queue_body(hg)
    log_unmapped(hg, logger)

    print(f'\nHunt group "{hg["name"]}" will be DELETED and recreated as a Call Queue:')
    print(f'  Location:  {summary.get("locationName", location_id)}')
    print(f'  Number:    {hg.get("phoneNumber", "")}  Extension: {hg.get("extension", "")}')
    print(f'  Policy:    {body["callPolicies"]["policy"]}')
    print(f'  Agents:    {len(agents)} (will be joined)')
    for a in agents:
        print(f'    - {a.get("firstName", "")} {a.get("lastName", "")} {a.get("extension", "")}'.rstrip())
    if not prompt_yes_no('Delete the hunt group and create the call queue?', default=False):
        logger.info('Migration declined by user.')
        logger.info(f'{TITLE} - Completed')
        return

    # Remove hunt group
    if api_send('DELETE', hg_url, headers, logger) is None:
        logger.error('Hunt group delete failed. Nothing was changed.')
        logger.info(f'{TITLE} - Completed')
        return
    logger.info(f'Hunt group deleted: {hg["name"]}')

    # Create call queue
    result = api_send('POST', f'{LOCATIONS_URL}/{location_id}/queues', headers, logger, body)
    if not result or not result.get('id'):
        logger.error(f'Call queue creation failed. The hunt group is already deleted; '
                     f're-create from backup {backup}')
        logger.info(f'{TITLE} - Completed')
        return
    logger.info(f'Call queue created: {hg["name"]} ({result["id"]})')

    if agents and not join_agents(location_id, result['id'], headers, logger):
        logger.error('Unable to confirm agents are joined. Check the queue in Control Hub.')

    logger.info(f'{TITLE} - Completed')


if __name__ == '__main__':
    main()
