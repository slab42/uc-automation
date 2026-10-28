#!/usr/bin/env python3
# TITLE: Buildings Check Entire Site

"""
Check that every Building in RedSky (E911) has a location under it named
"<Building Name> - Entire Site". Buildings missing that location are displayed,
logged and written to a CSV file. If no Building is missing it, the result is only
displayed and logged and no CSV is created.

Usage:
    python3 buildings_check_entire_site.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).

The location name is matched case-insensitively, ignoring extra spaces.

Output CSV (only written when Buildings are missing the location):
    _DATA/reports/<timestamp>-buildings_missing_entire_site.csv
    Columns: building, buildingId, expectedLocation

Logs: ../_logs/<timestamp>-buildings_check_entire_site.log
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
CSV_HEADER = ('building', 'buildingId', 'expectedLocation')
SUFFIX = ' - Entire Site'


def normalize(text):
    """Lowercase and collapse whitespace for name comparison."""
    return ' '.join(text.split()).lower()


def find_missing(redsky, logger, buildings):
    """
    Return the buildings that have no '<Building Name> - Entire Site' location.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        buildings (list): building dicts from RedSky
    Returns:
        list of (building, expected location name)
    """
    missing = []
    for building in buildings:
        name = building.get('name', '').strip()
        expected = f'{name}{SUFFIX}'
        locations = redsky.list_locations(building['id'])
        if any(normalize(loc.get('name', '')) == normalize(expected) for loc in locations):
            logger.debug('OK: %s (%d location(s))', name, len(locations))
        else:
            logger.warning('Missing "%s" under building %s', expected, name)
            missing.append((building, expected))
    return missing


def write_report(logger, missing):
    """Write the missing buildings to a CSV in _DATA/reports and return its path."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = REPORT_DIR / f'{timestamp}-buildings_missing_entire_site.csv'
    with open(path, 'w', encoding='utf-8', newline='') as report:
        writer = csv.writer(report)
        writer.writerow(CSV_HEADER)
        for building, expected in missing:
            writer.writerow((building.get('name', ''), building['id'], expected))
    logger.info('Wrote CSV: %s', path)
    return path


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-buildings_check_entire_site.log"
    logger = setup_logger(log_file)
    logger.info("Buildings Check Entire Site - Started")

    redsky = connect(logger)
    try:
        buildings = redsky.list_buildings()
        logger.info('Loaded %d building(s)', len(buildings))
        missing = find_missing(redsky, logger, buildings)
    except Exception as e:
        logger.error('Unable to check buildings in RedSky: %s', e)
        sys.exit(1)

    if missing:
        logger.info('%d of %d building(s) are missing the "%s" location:',
                    len(missing), len(buildings), SUFFIX.strip())
        for building, expected in missing:
            logger.info('  %s (expected: %s)', building.get('name', ''), expected)
        write_report(logger, missing)
    else:
        logger.info('All %d building(s) have a "<Building Name>%s" location. No CSV created.',
                    len(buildings), SUFFIX)

    logger.info("Buildings Check Entire Site - Completed")
