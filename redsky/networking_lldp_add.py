#!/usr/bin/env python3
# TITLE: Networking LLDP Add

"""
Add LLDP switches (chassis) and switch ports to RedSky (E911), individually or
from a list in CSV. A client whose LLDP data matches a chassis (and port) is
placed at the Location tied to it.

Usage:
    python3 networking_lldp_add.py

The script is interactive and will prompt for:
    Credentials: RedSky username, password and organization ID, taken from
        [REDSKY:default] in .env/credentials.env. Any missing value is
        requested at runtime (the password is never displayed).
    Use CSV?: (y/n): choose 'y' to bulk add from a CSV file,
        or 'n' (default) to add a single chassis or port.

    If 'n' (single entry):
        Chassis ID: the switch LLDP chassis ID (usually its base MAC address)
        Port ID: leave blank to add the chassis itself, or enter a port
            (e.g. Gi1/0/1) to add that port to the chassis
        Location: Location name, or 'Building / Location' when the name is
            used in more than one Building
        Description: optional

    If 'y' (CSV):
        Create a blank CSV template?: (y/n) writes a header-only CSV to the default
            path below and ends the script, so it can be opened and filled in.
        Enter CSV file name or full path: path to the CSV file
            (default: _DATA/networking_lldp_add.csv)

A row with a blank portId adds the chassis. A row with a portId adds that port
to the chassis; if the chassis is not in RedSky yet it is created first, with
no Location of its own. Put chassis rows before their port rows.
Location is matched by name, case-insensitively. A row whose Location is
unknown (or ambiguous across Buildings) is skipped and logged.

CSV format (chassisId, portId, location, description):
00:1A:2B:3C:4D:5E, , HQ Building / IDF 1, Floor 1 switch
00:1A:2B:3C:4D:5E, Gi1/0/1, HQ Building / Room 101, Desk jack 101-A
location is required; description is optional. Header row is skipped.

Logs: ../_logs/<timestamp>-networking_lldp_add.log
"""

import warnings
warnings.simplefilter('ignore')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from redskyCommon import connect, offer_csv_template, load_location_map, resolve_location, read_csv_rows, log_result, LOCATION_HELP

DEFAULT_CSV = Path(__file__).parent.parent / '_DATA' / 'networking_lldp_add.csv'
CSV_HEADER = ('chassisId', 'portId', 'location', 'description')


def load_switch_ids(redsky):
    """Return {lowercase chassisId: switch id} for the chassis already in RedSky."""
    return {sw.get('chassisId', '').strip().lower(): sw['id'] for sw in redsky.list_network_switches()}


def add_lldp(redsky, logger, location_map, switch_ids, chassis_id, port_id, location, description=''):
    """
    Add an LLDP chassis (blank port_id) or a port on a chassis.

    Args:
        redsky: RedSky client instance
        logger: logger instance
        location_map: lookup from load_location_map()
        switch_ids: {chassisId: switch id}; updated when a chassis is created
        chassis_id (string): Switch LLDP chassis ID
        port_id (string): Port ID, or blank to add the chassis itself
        location (string): Location name or 'Building / Location'
        description (string): Optional description
    """
    label = f'{chassis_id} {port_id}'.strip()
    location_id, error = resolve_location(location_map, location)
    if error:
        logger.error('%s: %s', label, error)
        return False

    key = chassis_id.lower()
    if not port_id:
        logger.info('Adding LLDP chassis %s at %s', chassis_id, location)
        result = redsky.add_network_switch(chassis_id, location_id, description)
        if result.get('success') and result.get('id'):
            switch_ids[key] = result['id']
        return log_result(logger, label, result)

    if key not in switch_ids:
        logger.info('Chassis %s not found in RedSky, creating it first', chassis_id)
        created = redsky.add_network_switch(chassis_id)
        if not log_result(logger, chassis_id, created):
            return False
        if created.get('id'):
            switch_ids[key] = created['id']
        else:
            switch_ids.update(load_switch_ids(redsky))
        if key not in switch_ids:
            logger.error('%s: unable to determine the new chassis id', chassis_id)
            return False
    logger.info('Adding LLDP port %s on chassis %s at %s', port_id, chassis_id, location)
    return log_result(logger, label, redsky.add_network_switch_port(port_id, switch_ids[key], location_id, description))


def run_single(redsky, logger, location_map, switch_ids):
    """
    Add a single LLDP chassis or port
    """
    print(LOCATION_HELP)
    chassis_id = input('Chassis ID: ').strip()
    port_id = input('Port ID (blank to add the chassis itself): ').strip()
    location = input('Location: ').strip()
    description = input('Description (optional): ').strip()
    if not (chassis_id and location):
        logger.error('Chassis ID and Location are required.')
        return
    add_lldp(redsky, logger, location_map, switch_ids, chassis_id, port_id, location, description)


def run_csv_file(redsky, logger, csv_file_path, location_map, switch_ids):
    """
    Bulk add LLDP chassis and ports from CSV
    """
    print('\nCSV Must have header row and must contain only 1 chassis or port per row')
    print('Field Order: chassisId, portId (blank for a chassis), location, description (optional)')
    succeeded = failed = 0
    for line, f in read_csv_rows(csv_file_path):
        if not (f[0] and f[2]):
            logger.error('Skipping line %d, chassisId and location are required', line)
            failed += 1
        elif add_lldp(redsky, logger, location_map, switch_ids, f[0], f[1], f[2], f[3]):
            succeeded += 1
        else:
            failed += 1
    logger.info('CSV complete: %d added, %d failed', succeeded, failed)


if __name__ == '__main__':
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-networking_lldp_add.log"
    logger = setup_logger(log_file)
    logger.info("Networking LLDP Add - Started")

    redsky = connect(logger)
    location_map = load_location_map(redsky, logger)
    switch_ids = load_switch_ids(redsky)
    logger.info('Loaded %d existing chassis', len(switch_ids))

    if prompt_yes_no('Use CSV?', default=False):
        if offer_csv_template(logger, DEFAULT_CSV, CSV_HEADER):
            logger.info("Networking LLDP Add - Completed")
            sys.exit(0)
        print('\nCSV Must have header row and must contain only 1 chassis or port per row')
        print('Field Order: chassisId, portId (blank for a chassis), location, description (optional)')
        csv_file = input(f'Enter CSV file name or full path [{DEFAULT_CSV}]: ').strip() or str(DEFAULT_CSV)
        run_csv_file(redsky, logger, csv_file, location_map, switch_ids)
    else:
        run_single(redsky, logger, location_map, switch_ids)

    logger.info("Networking LLDP Add - Completed")
