#!/usr/bin/env python3
# TITLE: Alerts Check All Buildings

"""
Check that every Building in RedSky (E911) has a matching alert subscription:
an alert named exactly like the Building (Building Foxden needs an alert named
Foxden) that has that Building in its subscribed locations (filters). Buildings
without a matching alert are displayed, logged and written to a CSV file. If
every Building has one, the result is only displayed and logged and no CSV is
created.

Usage:
    python3 alerts_check_all_buildings.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).

Alert names are matched case-insensitively, ignoring extra spaces. If several
alerts share the Building's name (for example different alert types), the
Building passes when any one of them has the Building as a subscribed location.

Output CSV (only written when Buildings are missing a matching alert):
    _DATA/reports/<timestamp>-buildings_missing_alert.csv
    Columns: building, buildingId, issue
    issue is 'No alert with this name' or 'Alert exists but Building is not a
    subscribed location'.

Logs: ../_logs/<timestamp>-alerts_check_all_buildings.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import csv
from datetime import datetime

from setup.logger import setup_logger
from redskyCommon import connect

REPORT_DIR = Path(__file__).parent.parent / '_DATA' / 'reports'
CSV_HEADER = ('building', 'buildingId', 'issue')
NO_ALERT = 'No alert with this name'
NOT_SUBSCRIBED = 'Alert exists but Building is not a subscribed location'


def normalize(text):
    """Lowercase and collapse whitespace for name comparison."""
    return ' '.join(text.split()).lower()


def find_missing(redsky, logger, buildings, subscriptions):
    """
    Return the buildings without a matching alert.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        buildings (list): building dicts from RedSky
        subscriptions (list): alert subscription dicts from RedSky
    Returns:
        list of (building, issue)
    """
    by_name = {}
    for sub in subscriptions:
        by_name.setdefault(normalize(sub.get('name', '')), []).append(sub)

    scoped_ids = {}
    missing = []
    for building in buildings:
        name = building.get('name', '').strip()
        matches = by_name.get(normalize(name), [])
        if not matches:
            logger.warning('No alert named %s', name)
            missing.append((building, NO_ALERT))
            continue
        subscribed = False
        for sub in matches:
            if sub['id'] not in scoped_ids:
                scoped_ids[sub['id']] = {f.get('ouId') for f in redsky.list_alert_subscription_filters(sub['id'])}
            if building['id'] in scoped_ids[sub['id']]:
                subscribed = True
                break
        if subscribed:
            logger.debug('OK: %s', name)
        else:
            logger.warning('Alert %s does not include the building as a subscribed location', name)
            missing.append((building, NOT_SUBSCRIBED))
    return missing


def write_report(logger, missing):
    """Write the buildings without a matching alert to a CSV in _DATA/reports and return its path."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = REPORT_DIR / f'{timestamp}-buildings_missing_alert.csv'
    with open(path, 'w', encoding='utf-8', newline='') as report:
        writer = csv.writer(report)
        writer.writerow(CSV_HEADER)
        for building, issue in missing:
            writer.writerow((building.get('name', ''), building['id'], issue))
    logger.info('Wrote CSV: %s', path)
    return path


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-alerts_check_all_buildings.log"
    logger = setup_logger(log_file)
    logger.info("Alerts Check All Buildings - Started")

    redsky = connect(logger)
    try:
        buildings = redsky.list_buildings()
        subscriptions = redsky.list_alert_subscriptions()
        logger.info('Loaded %d building(s) and %d alert(s)', len(buildings), len(subscriptions))
        missing = find_missing(redsky, logger, buildings, subscriptions)
    except Exception as e:
        logger.error('Unable to check alerts in RedSky: %s', e)
        sys.exit(1)

    if missing:
        logger.info('%d of %d building(s) are missing a matching alert:', len(missing), len(buildings))
        for building, issue in missing:
            logger.info('  %s: %s', building.get('name', ''), issue)
        write_report(logger, missing)
    else:
        logger.info('All %d building(s) have a matching alert. No CSV created.', len(buildings))

    logger.info("Alerts Check All Buildings - Completed")
