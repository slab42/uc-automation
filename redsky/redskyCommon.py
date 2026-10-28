"""
Helpers shared by the RedSky scripts: credentials, connecting, resolving location names
to ids, and reading operation CSV files.
"""

import warnings
warnings.simplefilter('ignore')

import csv
import getpass
import sys

from pathlib import Path

from setup.env_loader import CredentialsLoader
from setup.prompt_utils import prompt_yes_no
from redskyAPI import RedSky

LOCATION_HELP = ("Location is matched by name, case-insensitively. If the same name exists in more "
                 "than one Building, use 'Building / Location'.")


def load_redsky_credentials():
    """Return (username, password, org_id) from [REDSKY:default], prompting for anything missing."""
    creds = CredentialsLoader().get_redsky_credentials('default') or {}
    username = (creds.get('username') or '').strip()
    password = creds.get('password') or ''
    org_id = (creds.get('org_id') or '').strip()

    if not username:
        username = input('  Enter RedSky username: ').strip()
    if not password:
        print(f'  Username: {username}')
        password = getpass.getpass('  Enter RedSky password: ')
    if not org_id:
        org_id = input('  Enter RedSky organization ID: ').strip()
    return username, password, org_id


def connect(logger):
    """Prompt for credentials and return a logged-in RedSky client (exits on failure)."""
    username, password, org_id = load_redsky_credentials()
    if not (username and password and org_id):
        print("Error: RedSky username, password and organization ID are required")
        sys.exit(1)
    try:
        return RedSky(username=username, password=password, org_id=org_id, logger=logger)
    except Exception as e:
        logger.error('Unable to connect to RedSky: %s', e)
        sys.exit(1)


def load_location_map(redsky, logger):
    """
    Return {lowercase key: location id} for every location. Each location is keyed by
    its name and by 'building / name'. A name used in several Buildings maps to None
    (ambiguous) so it can only be addressed with the 'building / name' form.
    """
    location_map = {}
    for building, loc in redsky.list_all_locations():
        name = loc.get('name', '').strip().lower()
        keys = [name] + ([f'{building.strip().lower()} / {name}'] if building else [])
        for key in keys:
            location_map[key] = None if key in location_map else loc['id']
    logger.info('Loaded %d location(s)', len({v for v in location_map.values() if v}))
    return location_map


def resolve_location(location_map, text):
    """Return (location_id, error). error is '' on success."""
    key = ' / '.join(part.strip() for part in text.split('/')).lower()
    if key not in location_map:
        return None, f"unknown location: '{text}'"
    if location_map[key] is None:
        return None, f"location name '{text}' is used in more than one Building, use 'Building / Location'"
    return location_map[key], ''


def read_csv_rows(csv_file_path, width=10):
    """Yield (line_number, fields) for each non-blank row after the header; fields are stripped and padded."""
    with open(csv_file_path, 'r', encoding='utf-8-sig', newline='') as my_file:
        rows = csv.reader(my_file)
        next(rows, None)
        for row in rows:
            if any(field.strip() for field in row):
                yield rows.line_num, [f.strip() for f in row] + [''] * width


def offer_csv_template(logger, csv_path, header):
    """
    Offer to write a blank CSV (header row only) at csv_path so it can be opened and filled in.
    Returns True if a template was written; the caller should then end the script.
    """
    if not prompt_yes_no('Create a blank CSV template to fill in?', default=False):
        return False
    path = Path(csv_path)
    if path.exists() and not prompt_yes_no(f'{path} already exists. Overwrite?', default=False):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as template:
        csv.writer(template).writerow(header)
    logger.info('Created CSV template: %s', path)
    print('Fill in the template, then run this script again and choose the CSV option.')
    return True


def parse_bool(text):
    """Return True/False for yes/no style text, or None when blank or unrecognized."""
    value = text.strip().lower()
    if value in ('yes', 'y', 'true', '1'):
        return True
    if value in ('no', 'n', 'false', '0'):
        return False
    return None


def split_list(text):
    """Split a semicolon separated CSV cell into a list of non-blank, stripped items."""
    return [item.strip() for item in text.split(';') if item.strip()]


def log_result(logger, label, result):
    """Log a create result and return True on success."""
    if result.get('success'):
        logger.info(result.get('response'))
        return True
    logger.error('%s: %s', label, result.get('error'))
    return False
