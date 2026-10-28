#!/usr/bin/env python3
# TITLE: Alerts Add

"""
Add Alert Subscriptions to RedSky (E911), individually or from a list in CSV.
A subscription says who is notified (email and SMS) when an alert type such as
an emergency call occurs, and optionally which Buildings or Locations it covers.

Usage:
    python3 alerts_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add subscriptions from a CSV file,
        or 'n' (default) to add a single subscription.

    If 'n' (single subscription):
        Subscription Name
        Select Alert Type: numbered list of the alert types in RedSky
        Select Template: numbered list of the templates for that alert type
            (0 uses no template)
        Email Recipients / SMS Recipients: separate several with semicolons
        Timezone: optional, e.g. America/Chicago
        All Corporate Locations / All Personal Locations: (y/n)
        Scope: optional list of Buildings and Locations, separated by
            semicolons. Leave blank for no scope filters.

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/alerts_add.csv)

Alert type is matched by machine name or display text, template by name, both
case-insensitively. A scope entry is a Building name, or a Location name
('Building / Location' if the name exists in more than one Building). A
name that is both a Building and a Location is treated as the Building.
A row with an unknown alert type, template or scope entry is skipped and logged.
If the subscription is created but its scope filters fail, the error is logged
and the subscription must be corrected in RedSky.

CSV format (name, alertType, template, emailRecipients, smsRecipients, timezone,
allCorporateLocations, allPersonalLocations, scope):
HQ 911 Calls, EMERGENCY_CALL, Default Email, a@example.com;b@example.com, +12175550100, America/Chicago, no, no, HQ Building;Branch Office
Only name and alertType are required. Separate several recipients or scope
entries with semicolons. The two "all" columns accept yes/no/true/false/1/0.
Header row is skipped.

Logs: ../_logs/<timestamp>-alerts_add.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from redskyCommon import (connect, offer_csv_template, load_location_map, resolve_location, read_csv_rows,
                          log_result, parse_bool, split_list)

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'alerts_add.csv'
CSV_HEADER = ('name', 'alertType', 'template', 'emailRecipients', 'smsRecipients', 'timezone',
          'allCorporateLocations', 'allPersonalLocations', 'scope')


def template_type(template):
    """Return the alert type name of a raw template dict ('' if absent)."""
    alert_type = template.get('alertType') or template.get('alertTypeTO') or {}
    return alert_type.get('name', '') if isinstance(alert_type, dict) else str(alert_type)


def resolve_alert_type(alert_types, text):
    """Return ((name, text), error) matching a machine name or display text."""
    for name, display in alert_types.items():
        if text.lower() in (name.lower(), display.lower()):
            return (name, display), ''
    return None, f"unknown alert type: '{text}'"


def resolve_template(templates, alert_type_name, text):
    """Return (template_id, error) matching a template by name within an alert type."""
    matches = [t for t in templates
               if t.get('name', '').strip().lower() == text.lower()
               and template_type(t) in ('', alert_type_name)]
    if not matches:
        return None, f"unknown template for {alert_type_name}: '{text}'"
    return matches[0]['id'], ''


def resolve_scope(entries, building_ids, location_map):
    """Return ([(ou_id, filter_type)], error) for Building and Location names."""
    filters = []
    for entry in entries:
        if '/' not in entry and entry.lower() in building_ids:
            filters.append((building_ids[entry.lower()], 'BUILDING'))
            continue
        location_id, error = resolve_location(location_map, entry)
        if error:
            return None, f"scope entry '{entry}' is not a known building, or {error}"
        filters.append((location_id, 'LOCATION'))
    return filters, ''


def add_alert(redsky, logger, lookups, name, alert_type, template, emails, sms,
              timezone, all_corporate, all_personal, scope):
    """
    Add an alert subscription and, if a scope is given, its filters.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        lookups (dict): alert_types, templates, building_ids, location_map
        name (string): Subscription name
        alert_type (string): Alert type name or display text
        template (string): Template name, or blank for none
        emails (list): Email recipients
        sms (list): SMS recipient phone numbers
        timezone (string): Optional timezone
        all_corporate (bool): Apply to all corporate locations
        all_personal (bool): Apply to all personal locations
        scope (list): Building and Location names to limit the subscription to
    """
    type_pair, error = resolve_alert_type(lookups['alert_types'], alert_type)
    template_id = None
    filters = []
    if not error and template:
        template_id, error = resolve_template(lookups['templates'], type_pair[0], template)
    if not error and scope:
        filters, error = resolve_scope(scope, lookups['building_ids'], lookups['location_map'])
    if error:
        logger.error('%s: %s', name, error)
        return False

    logger.info('Adding alert subscription %s (%s)', name, type_pair[0])
    result = redsky.add_alert_subscription(name, type_pair, template_id, emails, sms, timezone,
                                           all_corporate, all_personal)
    if not log_result(logger, name, result):
        return False
    if filters:
        if not result.get('id'):
            logger.error('%s: created, but RedSky did not return its id so the scope was not set', name)
            return False
        return log_result(logger, f'{name} scope', redsky.set_alert_subscription_filters(result['id'], filters))
    return True


def load_lookups(redsky, logger):
    """Fetch the alert types, templates, buildings and locations used to resolve names."""
    buildings = redsky.list_buildings()
    lookups = {
        'alert_types': redsky.list_alert_types(),
        'templates': redsky.list_alert_templates(),
        'building_ids': {b.get('name', '').strip().lower(): b['id'] for b in buildings},
        'location_map': load_location_map(redsky, logger),
    }
    logger.info('Loaded %d alert type(s), %d template(s), %d building(s)',
                len(lookups['alert_types']), len(lookups['templates']), len(buildings))
    return lookups


def select_from(prompt, options, allow_none=False):
    """Numbered menu. Returns the chosen option, or '' for 0 when allow_none."""
    print()
    if allow_none:
        print('  0. (none)')
    for i, option in enumerate(options, 1):
        print(f'  {i}. {option}')
    low = 0 if allow_none else 1
    while True:
        choice = input(f'{prompt} [{low}-{len(options)}]: ').strip()
        if choice.isdigit() and low <= int(choice) <= len(options):
            return '' if int(choice) == 0 else options[int(choice) - 1]
        print('Invalid selection.')


def run_single(redsky, logger, lookups):
    """
    Add a single alert subscription
    """
    name = input('Subscription Name: ').strip()
    if not name:
        logger.error('Subscription Name is required.')
        return
    type_names = [f'{n} ({t})' for n, t in lookups['alert_types'].items()]
    chosen = select_from('Select Alert Type', type_names)
    alert_type = chosen.split(' (')[0]
    templates = sorted({t.get('name', '') for t in lookups['templates']
                        if template_type(t) in ('', alert_type) and t.get('name')})
    template = select_from('Select Template', templates, allow_none=True) if templates else ''
    emails = split_list(input('Email Recipients (separate with ;): '))
    sms = split_list(input('SMS Recipients (separate with ;): '))
    timezone = input('Timezone (optional, e.g. America/Chicago): ').strip()
    all_corporate = prompt_yes_no('All Corporate Locations?', default=False)
    all_personal = prompt_yes_no('All Personal Locations?', default=False)
    scope = split_list(input('Scope: Buildings/Locations (separate with ;, optional): '))
    add_alert(redsky, logger, lookups, name, alert_type, template, emails, sms,
              timezone, all_corporate, all_personal, scope)


def run_csv_file(redsky, logger, csv_file_path, lookups):
    """
    Bulk add alert subscriptions from CSV
    """
    print('\nCSV Must have header row and must contain only 1 subscription per row')
    print('Field Order: name, alertType, template, emailRecipients, smsRecipients, timezone, '
          'allCorporateLocations, allPersonalLocations, scope')
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        if not (f[0] and f[1]):
            logger.error('Skipping line %d, name and alertType are required', line)
            failed += 1
        elif add_alert(redsky, logger, lookups, f[0], f[1], f[2], split_list(f[3]), split_list(f[4]),
                       f[5], bool(parse_bool(f[6])), bool(parse_bool(f[7])), split_list(f[8])):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-alerts_add.log"
    logger = setup_logger(log_file)
    logger.info("Alerts Add - Started")

    redsky = connect(logger)
    try:
        lookups = load_lookups(redsky, logger)
    except Exception as e:
        logger.error('Unable to load alert data from RedSky: %s', e)
        sys.exit(1)

    if prompt_yes_no('Use CSV?', default=False):
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Alerts Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 subscription per row')
        print('Field Order: name, alertType, template, emailRecipients, smsRecipients, timezone, '
              'allCorporateLocations, allPersonalLocations, scope')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file, lookups)
    else:
        run_single(redsky, logger, lookups)

    logger.info("Alerts Add - Completed")
