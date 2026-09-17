#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Extension Mobility (EM) Bulk Operations Script

Reads em_users.csv and loads Extension Mobility AppServlet URLs to trigger
login, logout, or check sessions in bulk.

CSV Format (single file for all modes):
  device, user, pin
  Example:
    SEPDC0539FB8FA2, CCMarquez, 159357
    SEPDC0539FB8FA3, JSmith, 987654

LOGIN Mode:
  Uses device, user, and pin from CSV to log in users
  URL Format: http://server:8080/emapp/EMAppServlet?device=SEPDC0539FB8FA2&userid=CCMarquez&seq=159357

LOGOUT Mode:
  Uses device from CSV to log out users (ignores user and pin)
  URL Format: http://server:8080/emapp/EMAppServlet?device=SEPDC0539FB8FA2&doLogout=true

CHECK Mode:
  Validates if users from CSV are logged in on their phones
  URL Format: http://server:8080/emapp/EMAppServlet?device=SEPDC0539FB8FA2&check=true

Usage:
  python3 em_bulk_login.py

  Prompts for:
  1. Operation mode: login, logout, or check (default: login)
  2. Extension Mobility server FQDN or IP address

  CSV file location: _DATA/em_users.csv
  Logs output to: ../_logs/{timestamp}-em-bulk-login.log
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import csv
import requests
import urllib3
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from setup.logger import setup_logger
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL

# Extension Mobility configuration
EM_PORT = 8080


def setup_http_session():
    """Setup HTTP session with retry logic."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    retry_strategy = Retry(total=3, status_forcelist=[429, 500, 502, 503, 504],
                          allowed_methods=["HEAD", "GET", "OPTIONS", "POST"])
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_operation_mode():
    """Prompt user for operation mode: login, logout, or check."""
    while True:
        mode = input("Select operation mode (login/logout/check) [login]: ").strip().lower()
        if mode in ('', 'login'):
            return 'login'
        elif mode == 'logout':
            return 'logout'
        elif mode == 'check':
            return 'check'
        else:
            print("Invalid selection. Please enter 'login', 'logout', or 'check'.")


def get_em_server():
    """Prompt user for Extension Mobility server address."""
    server = input("Enter Extension Mobility server FQDN or IP address: ").strip()
    while not server:
        print("Server address cannot be empty.")
        server = input("Enter Extension Mobility server FQDN or IP address: ").strip()
    return server


def read_em_data(basepath):
    """
    Read Extension Mobility data from CSV.

    Returns:
        List of dicts with keys: device, user, pin
    """
    csv_file = basepath.parent / '_DATA' / 'em_users.csv'
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    data = []
    with open(csv_file, 'r') as f:
        next(f)  # Skip header row
        csv_reader = csv.DictReader(f, fieldnames=['device', 'user', 'pin'])
        for row_num, row in enumerate(csv_reader, start=1):
            if not row['device'] or not row['user'] or not row['pin']:
                print(f"Warning: Row {row_num} has missing fields, skipping")
                continue
            data.append({
                'device': row['device'].strip(),
                'user': row['user'].strip(),
                'pin': row['pin'].strip()
            })

    return data


def build_em_url(server, port, device, mode, user=None, pin=None):
    """
    Build Extension Mobility AppServlet URL.

    Args:
        server: FQDN or IP of EM server
        port: Port number
        device: Device ID (e.g., SEPDC0539FB8FA2)
        mode: 'login', 'logout', or 'check'
        user: User ID (for login mode)
        pin: PIN/sequence number (for login mode)

    Returns:
        Full URL string
    """
    base_url = f"http://{server}:{port}/emapp/EMAppServlet"
    if mode == 'login':
        params = f"?device={device}&userid={user}&seq={pin}"
    elif mode == 'logout':
        params = f"?device={device}&doLogout=true"
    else:  # check
        params = f"?device={device}&check=true"
    return base_url + params


def load_em_urls(data, server, port, session, logger, mode, axl_client=None):
    """
    Load each Extension Mobility URL or check login status.

    Args:
        data: List of dicts with device info
        server: EM server address
        port: EM port
        session: requests.Session with retry logic
        logger: Logger instance
        mode: 'login', 'logout', or 'check'
        axl_client: AXL client instance (required for check mode)
    """
    results = {
        'total': len(data),
        'success': 0,
        'failed': 0,
        'errors': []
    }

    for idx, item in enumerate(data, start=1):
        device = item['device']

        if mode == 'login':
            user = item['user']
            pin = item['pin']
            url = build_em_url(server, port, device, mode, user=user, pin=pin)
            log_msg = f"[{idx}/{results['total']}] Logging in: device={device}, user={user}"
            success_msg = f"✓ Logged in: {device} - {user} (HTTP {{}})"
            error_ref = f"{device}/{user}"
        elif mode == 'logout':
            url = build_em_url(server, port, device, mode)
            log_msg = f"[{idx}/{results['total']}] Logging out: device={device}"
            success_msg = f"✓ Logged out: {device} (HTTP {{}})"
            error_ref = device
        else:  # check
            user = item['user']
            log_msg = f"[{idx}/{results['total']}] Checking: device={device}, user={user}"
            error_ref = f"{device}/{user}"

            logger.info(log_msg)

            try:
                # Use AXL to check device login status
                check_result = axl_client.check_device_login(device)
                logger.debug(f"Check result: {check_result}")

                # Log SOAP history for debugging
                if not check_result.get('success'):
                    try:
                        from lxml import etree
                        for item in axl_client.history.requests:
                            logger.debug(f"SOAP Request: {etree.tostring(item['envelope'], pretty_print=True).decode()}")
                        for item in axl_client.history.responses:
                            logger.debug(f"SOAP Response: {etree.tostring(item['envelope'], pretty_print=True).decode()}")
                    except Exception as hist_err:
                        logger.debug(f"Could not log SOAP history: {hist_err}")

                if check_result.get('success'):
                    if check_result.get('logged_in'):
                        logged_user = check_result.get('user', 'Unknown')
                        if logged_user.lower() == user.lower():
                            logger.info(f"✓ Logged in: {device} - {logged_user}")
                            results['success'] += 1
                        else:
                            logger.warning(f"✗ Wrong user: {device} - Expected {user}, found {logged_user}")
                            results['failed'] += 1
                            results['errors'].append(f"{error_ref}: Wrong user logged in ({logged_user})")
                    else:
                        logger.warning(f"✗ Not logged in: {device}")
                        results['failed'] += 1
                        results['errors'].append(f"{device}: No user logged in")
                else:
                    error_msg = check_result.get('error', 'Unknown error')
                    logger.error(f"✗ Error checking: {error_ref} - {error_msg}")
                    results['failed'] += 1
                    results['errors'].append(f"{error_ref}: {error_msg}")
            except Exception as e:
                logger.error(f"✗ Exception: {error_ref}: {str(e)}")
                logger.debug(f"Exception details: {type(e).__name__}: {str(e)}")
                results['failed'] += 1
                results['errors'].append(f"{error_ref}: {str(e)}")

            continue  # Skip the normal HTTP request handling below for check mode

        logger.info(log_msg)
        logger.debug(f"URL: {url}")

        try:
            response = session.get(url, timeout=10, verify=False)
            if response.status_code == 200:
                logger.info(success_msg.format(response.status_code))
                results['success'] += 1
            else:
                logger.warning(f"✗ HTTP {response.status_code}: {error_ref}")
                results['failed'] += 1
                results['errors'].append(f"{error_ref}: HTTP {response.status_code}")
        except requests.exceptions.Timeout:
            logger.error(f"✗ Timeout: {error_ref}")
            results['failed'] += 1
            results['errors'].append(f"{error_ref}: Timeout")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"✗ Connection error: {error_ref}: {str(e)}")
            results['failed'] += 1
            results['errors'].append(f"{error_ref}: Connection error")
        except Exception as e:
            logger.error(f"✗ Error: {error_ref}: {str(e)}")
            results['failed'] += 1
            results['errors'].append(f"{error_ref}: {str(e)}")

    return results


def print_summary(results, logger):
    """Print summary of bulk operation results."""
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"EM Bulk Operation Summary")
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
    print("")  # Blank line to stdout for readability


def run_check_on_cluster(basepath, cluster_data, data, cluster_credentials, logger):
    """Run EM check operation on a single cluster."""
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = cluster_credentials[cluster_name]

        # Setup AXL Connection to CUCM
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl_client = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        results = load_em_urls(data, None, None, None, logger, 'check', axl_client=axl_client)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return results
    except Exception as e:
        logger.error(f"✗ Failed on {cluster_name}: {str(e)}")
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return None


def run_check_on_all_clusters(basepath, clusters_data, data, logger):
    """Run check operation on all clusters sequentially."""
    print(f"\nProcessing {len(clusters_data)} clusters for device check...\n")

    # Load credentials using the new loader
    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = input('Use same credentials for all clusters? (y/n) [default: y]: ').strip().lower()
    use_same = use_same in ('', 'y', 'yes')

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    combined_results = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'errors': []
    }

    for cluster in clusters_data:
        results = run_check_on_cluster(basepath, cluster, data, cluster_credentials, logger)
        if results:
            combined_results['total'] += results['total']
            combined_results['success'] += results['success']
            combined_results['failed'] += results['failed']
            combined_results['errors'].extend(results['errors'])

    print(f"\n{'=' * 60}")
    print(f"Overall: {combined_results['success']} successful, {combined_results['failed']} failed across {len(clusters_data)} clusters")
    print(f"{'=' * 60}")

    return combined_results


def main(basepath, logger, mode, data, em_server=None, use_multiple_clusters=False, clusters_data=None):
    """Main execution."""
    try:
        # Read EM data CSV
        csv_file_path = basepath.parent / '_DATA' / 'em_users.csv'
        logger.info(f"CSV File: {csv_file_path}")
        logger.info("")

        if mode == "login":
            action = "login"
        elif mode == "logout":
            action = "logout"
        else:
            action = "check"
        print(f"Loaded {len(data)} records for {action} from {csv_file_path}\n")
        logger.info(f"Loaded {len(data)} records")

        # Handle check mode with cluster support
        if mode == "check":
            if use_multiple_clusters and clusters_data:
                results = run_check_on_all_clusters(basepath, clusters_data, data, logger)
            else:
                cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='em')
                if not cluster:
                    print("Error: Unable to load CUCM cluster information")
                    logger.error("Unable to load CUCM cluster information")
                    sys.exit(1)

                username, password = load_credentials('CUCM', cluster['name'])
                server = cluster['server']
                version = cluster['version']

                wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
                wsdl = wsdl_dir.absolute().as_uri()
                axl_client = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)
                logger.info(f"CUCM Cluster: {cluster['name']} ({server})")
                results = load_em_urls(data, None, None, None, logger, mode, axl_client=axl_client)

        else:
            # Login/Logout mode
            logger.info(f"EM Server: {em_server}:{EM_PORT}")

            # Setup HTTP session with retries
            session = setup_http_session()
            results = load_em_urls(data, em_server, EM_PORT, session, logger, mode)

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
    # Quick debug mode: python3 em_bulk_login.py debug SEP5006AB80ED92
    if len(sys.argv) > 1 and sys.argv[1] == 'debug':
        if len(sys.argv) < 3:
            print("Usage: python3 em_bulk_login.py debug <device_name>")
            sys.exit(1)

        device = sys.argv[2]
        basepath = Path(__file__).parent

        # Load cluster and credentials
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='em')
        if not cluster:
            print("Error: Unable to load CUCM cluster")
            sys.exit(1)

        username, password = load_credentials('CUCM', cluster['name'])
        server = cluster['server']
        version = cluster['version']

        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl_client = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        print(f"\nDEBUG: Querying device {device}...")
        phone_data = axl_client.debug_get_phone(device)
        print(f"\nPhone object (first 2000 chars):\n{str(phone_data)[:2000]}")
        sys.exit(0)

    # Normal execution
    basepath = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-em-bulk-login.log"
    logger = setup_logger(log_file)
    logger.info("Extension Mobility Bulk Login/Logout/Check - Started")

    print("\n" + "=" * 60)
    print("Extension Mobility Bulk Operations")
    print("=" * 60 + "\n")

    # Get operation mode
    mode = get_operation_mode()
    logger.info(f"Operation Mode: {mode.upper()}")

    # Read EM data
    data = read_em_data(basepath)
    if not data:
        msg = "No valid records found in CSV file."
        print(msg)
        logger.error(msg)
        sys.exit(1)

    # Handle cluster checking for check mode
    use_multiple_clusters = False
    clusters_data = None
    em_server = None

    if mode == "check":
        clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='em')
        if clusters_data:
            response = input(f'{len(clusters_data)} clusters found. Use multiple clusters? (y/n) [default: n]: ') or 'n'
            if response.lower() in ('y', 'yes'):
                use_multiple_clusters = True
    else:
        # For login/logout, get EM server
        em_server = get_em_server()

    # Run main operation
    main(basepath, logger, mode, data, em_server=em_server, use_multiple_clusters=use_multiple_clusters, clusters_data=clusters_data)
