#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Set User PIN Script

Reads em_users.csv and sets the PIN (Extension Mobility PIN) on each user in CUCM.

CSV Format:
  device, user, pin
  Example:
    SEPBC8D1F71159C, apezon, 159357
    SEP80276CBE24B0, amejia, 159357

The script extracts the user and pin columns and updates each user's EM PIN via CUCM AXL API.

Usage:
  python3 set_user_pin.py

  Prompts for:
  1. CUCM cluster selection
  2. Credentials (if not stored)
  3. Single user or CSV mode
     - Single: Enter user ID and PIN manually
     - CSV: Uses em_users.csv from _DATA folder

  Logs output to: ../_logs/{timestamp}-set-user-pin.log
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import csv
import urllib3
from datetime import datetime
from setup.logger import setup_logger
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL


def read_user_pin_data(basepath):
    """
    Read user and pin data from CSV.

    Returns:
        List of dicts with keys: user, pin
    """
    csv_file = basepath.parent / '_DATA' / 'em_users.csv'
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    data = []
    with open(csv_file, 'r') as f:
        next(f)  # Skip header row
        csv_reader = csv.DictReader(f, fieldnames=['device', 'user', 'pin'])
        for row_num, row in enumerate(csv_reader, start=1):
            if not row['user'] or not row['pin']:
                print(f"Warning: Row {row_num} has missing user or pin, skipping")
                continue
            data.append({
                'user': row['user'].strip(),
                'pin': row['pin'].strip()
            })

    return data


def set_user_pins(data, axl_client, logger):
    """
    Set PIN on each user in CUCM.

    Args:
        data: List of dicts with user and pin info
        axl_client: AXL client instance
        logger: Logger instance

    Returns:
        Dict with results summary
    """
    results = {
        'total': len(data),
        'success': 0,
        'failed': 0,
        'errors': []
    }

    for idx, item in enumerate(data, start=1):
        user = item['user']
        pin = item['pin']

        log_msg = f"[{idx}/{results['total']}] Setting PIN for user: {user}"
        logger.info(log_msg)

        try:
            # Update user with new PIN via AXL
            axl_result = axl_client.update_User(userid=user, pin=pin)

            if axl_result.get('success'):
                logger.info(f"✓ PIN set for: {user}")
                results['success'] += 1
            else:
                error_msg = axl_result.get('error', 'Unknown error')
                logger.warning(f"✗ Failed to set PIN for {user}: {error_msg}")
                results['failed'] += 1
                results['errors'].append(f"{user}: {error_msg}")

        except Exception as e:
            logger.error(f"✗ Exception setting PIN for {user}: {str(e)}")
            results['failed'] += 1
            results['errors'].append(f"{user}: {str(e)}")

    return results


def print_summary(results, logger):
    """Print summary of bulk operation results."""
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Set User PIN Summary")
    logger.info("=" * 60)
    logger.info(f"Total:   {results['total']}")
    logger.info(f"Success: {results['success']}")
    logger.info(f"Failed:  {results['failed']}")

    if results['errors']:
        logger.info("")
        logger.info("Errors:")
        for error in results['errors']:
            logger.info(f"  - {error}")

    logger.info("=" * 60)
    print("")


def main(basepath, logger, data, axl_client):
    """Main execution."""
    try:
        csv_file_path = basepath.parent / '_DATA' / 'em_users.csv'
        logger.info(f"CSV File: {csv_file_path}")
        logger.info("")

        print(f"Loaded {len(data)} records from {csv_file_path}\n")
        logger.info(f"Loaded {len(data)} records")

        # Set user PINs
        results = set_user_pins(data, axl_client, logger)

        # Print summary
        print_summary(results, logger)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        logger.info("Operation cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    basepath = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-set-user-pin.log"
    logger = setup_logger(log_file)
    logger.info("Set User PIN Script - Started")

    print("\n" + "=" * 60)
    print("Set User PIN")
    print("=" * 60 + "\n")

    # Load cluster and credentials
    cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
    if not cluster:
        print("Error: Unable to load CUCM cluster information")
        logger.error("Unable to load CUCM cluster information")
        sys.exit(1)

    username, password = load_credentials('CUCM', cluster['name'])
    server = cluster['server']
    version = cluster['version']

    logger.info(f"CUCM Cluster: {cluster['name']} ({server})")

    # Setup AXL Connection
    wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdl_dir.absolute().as_uri()
    axl_client = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

    # Test AXL connection
    logger.info("Testing AXL connection...")
    conn_test = axl_client.get_CCMVersion()
    if not conn_test.get('success'):
        msg = f"AXL connection failed: {conn_test.get('error', 'Unknown error')}"
        print(msg)
        logger.error(msg)
        sys.exit(1)
    logger.info(f"✓ Connected to CUCM: {conn_test.get('response')}")

    # Read user PIN data
    data = read_user_pin_data(basepath)
    if not data:
        msg = "No valid records found in CSV file."
        print(msg)
        logger.error(msg)
        sys.exit(1)

    # Run main operation
    main(basepath, logger, data, axl_client)
