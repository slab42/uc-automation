#!/usr/bin/env python3
"""
Cisco Router Platform Software Status Checker

Connects to multiple Cisco routers via SSH and executes:
  show platform software status control-processor br

Customer Variables - Imported from ../.var/check_router_mem_status.var
  low_memory_threshold - Free memory percentage threshold for alerts (default: 33)

Router list from CSV file (required):
  router_ip,hostname
  192.168.1.1,router-01
  192.168.1.2,router-02

Credentials from:
  - Interactive prompt (enter username/password at runtime)
  - credentials.env file:
    [CUBE:default] - Single credential set for all routers
    [CUBE:hostname] - Per-router credentials matched by hostname

See .env.EXAMPLE/CREDENTIALS_ENV_README.md for credentials.env setup.
"""

import warnings
warnings.filterwarnings('ignore')

import argparse
import csv
import getpass
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

# SSH connection settings
SSH_DEVICE_TYPE = 'cisco_ios'
SSH_PORT = 22
SSH_TIMEOUT = 15

# Add parent directory to path to import from setup
sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.logger import setup_logger
from setup.env_loader import EnvironmentConfig, CredentialsLoader
from setup.var_loader import load_customer_variables

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except ImportError:
    print("ERROR: netmiko not installed. Install with: pip install netmiko")
    sys.exit(1)


def extract_memory_section(output):
    """Extract the Memory section from router output."""
    lines = output.split('\n')
    memory_section = []
    in_memory = False

    for line in lines:
        if 'Memory (kB)' in line:
            in_memory = True

        if in_memory:
            memory_section.append(line)
            if memory_section and len(memory_section) > 1 and line.strip() and not line[0].isspace():
                if 'Memory' not in line:
                    memory_section.pop()
                    break

    return '\n'.join(memory_section) if memory_section else "Memory section not found"


def extract_free_percentage(output):
    """Extract the Free (Pct) value from router output."""
    lines = output.split('\n')

    for line in lines:
        if 'RP0' in line or 'RP1' in line:
            parts = line.split()
            percentages = []
            for part in parts:
                if part.endswith('%)') and '(' in part:
                    pct_str = part.strip('()%')
                    try:
                        percentages.append(int(pct_str))
                    except ValueError:
                        continue
            if len(percentages) >= 2:
                return percentages[1]

    return 0


def read_csv_routers(csv_path):
    """Read router list from CSV file. Searches for router_ip and hostname columns."""
    routers = []
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                print("ERROR: CSV file is empty")
                return None

            ip_col = next((h for h in reader.fieldnames if h.lower() in ['router_ip', 'ip', 'address']), None)
            host_col = next((h for h in reader.fieldnames if h.lower() in ['hostname', 'name', 'router_name']), None)

            if not ip_col or not host_col:
                print(f"ERROR: CSV must contain 'router_ip' and 'hostname' columns. Found: {reader.fieldnames}")
                return None

            for row in reader:
                routers.append({
                    'ip': row[ip_col].strip(),
                    'hostname': row[host_col].strip()
                })

        return routers if routers else None
    except FileNotFoundError:
        print(f"ERROR: File not found: {csv_path}")
        return None
    except Exception as e:
        print(f"ERROR: Failed to read CSV: {e}")
        return None


def send_summary_email(results, timestamp, logger, email_cfg, low_memory_threshold):
    """Send a summary email with router check results."""
    try:
        body = f"Router Memory Status Check - {timestamp}\n"
        body += "=" * 80 + "\n\n"

        successful = sum(1 for r in results if r['success'])
        body += f"Summary: {successful}/{len(results)} routers successful\n\n"

        for result in results:
            status = "✓ SUCCESS" if result['success'] else "✗ FAILED"
            highlight = " ⚠️ LOW FREE MEMORY" if result['success'] and result['free_pct'] < low_memory_threshold else ""
            body += f"{status} - {result['hostname']} ({result['ip']}){highlight}\n"
            if result['success']:
                body += f"  Memory Info: {result['memory']}\n"
            body += "\n"

        msg = MIMEMultipart()
        msg['From'] = email_cfg['source_email']
        msg['To'] = email_cfg['destination_email']
        msg['Subject'] = f"Router Memory Status Check - {timestamp}"
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(email_cfg['mail_server'], email_cfg['mail_port'])
        server.send_message(msg)
        server.quit()

        logger.info(f"Summary email sent to {email_cfg['destination_email']}")
        print(f"✓ Summary email sent to {email_cfg['destination_email']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send summary email: {e}")
        print(f"ERROR: Failed to send summary email: {e}")
        return False


def check_router_status(device_config, logger):
    """Connect to router and execute show platform software status command."""
    router_ip = device_config['ip']
    hostname = device_config['hostname']

    logger.info(f"Connecting to {hostname} ({router_ip})...")
    print(f"\n{'='*80}")
    print(f"Router: {hostname} ({router_ip})")
    print(f"{'='*80}")

    netmiko_params = {k: v for k, v in device_config.items() if k not in ['ip', 'hostname']}

    try:
        with ConnectHandler(**netmiko_params) as net_connect:
            logger.info(f"Connected to {hostname}")
            output = net_connect.send_command("show platform software status control-processor br")
            logger.info(f"Command executed successfully on {hostname}")
            print(output)
            return {'success': True, 'output': output}
    except NetmikoAuthenticationException as e:
        error_msg = f"Authentication failed for {hostname}: {e}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}")
        return {'success': False, 'output': ''}
    except NetmikoTimeoutException as e:
        error_msg = f"Connection timeout for {hostname}: {e}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}")
        return {'success': False, 'output': ''}
    except Exception as e:
        error_msg = f"Failed to connect to {hostname}: {e}"
        logger.error(error_msg)
        print(f"ERROR: {error_msg}")
        return {'success': False, 'output': ''}


def main():
    parser = argparse.ArgumentParser(description='Check Cisco router memory status')
    parser.add_argument('-d', '--default', action='store_true', help='Accept defaults for all prompts without user interaction')
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-check_router_status.log"
    logger = setup_logger(log_file)

    # Load customer variables from .var file
    customer_vars = load_customer_variables(__file__, logger, skip_prompts=args.default)
    low_memory_threshold = int(customer_vars.get('low_memory_threshold', 10)) if customer_vars else 10

    env_config = EnvironmentConfig()
    email_cfg = env_config.get_email_config()

    logger.info("Router Status Check - Started")

    # Step 1: Read router list from CSV
    print("\n" + "="*80)
    if args.default:
        csv_input = "../_DATA/routers.csv"
        logger.info("Using default CSV path (--default flag set)")
    else:
        csv_input = input("Enter path to CSV file [_DATA/routers.csv]: ").strip()
        if not csv_input:
            csv_input = "../_DATA/routers.csv"

    routers = read_csv_routers(csv_input)
    if not routers:
        logger.error("No routers found in CSV file")
        return

    logger.info(f"Found {len(routers)} router(s) to check")
    print(f"\nFound {len(routers)} router(s):")
    for r in routers:
        print(f"  - {r['hostname']} ({r['ip']})")

    # Step 2: Choose credential mode
    print("\n" + "="*80)
    print("Credential Mode")
    print("="*80)
    print("1. Single username/password for all routers")
    print("2. Per-router credentials (matched by hostname in credentials.env)")
    if args.default:
        cred_mode = "1"
        print("\nUsing default mode: 1 (single username/password)")
        logger.info("Using default credential mode (--default flag set)")
    else:
        cred_mode = input("\nSelect mode (1 or 2) [default: 1]: ").strip() or "1"

    devices = []
    creds_loader = CredentialsLoader()

    if cred_mode == "2":
        # Per-router credentials mode
        logger.info("Using per-router credentials from credentials.env")
        cube_creds = creds_loader.get_cube_credentials()

        if not cube_creds:
            logger.warning("No credentials found in credentials.env, falling back to prompt")
            print("\nWARNING: No credentials found in credentials.env")
            print("Falling back to interactive prompt...")
            username = input("Enter SSH username: ").strip()
            password = getpass.getpass("Enter SSH password: ")
            for router in routers:
                devices.append({
                    'device_type': SSH_DEVICE_TYPE,
                    'host': router['ip'],
                    'username': username,
                    'password': password,
                    'port': SSH_PORT,
                    'timeout': SSH_TIMEOUT,
                    'ip': router['ip'],
                    'hostname': router['hostname']
                })
        else:
            # Build credential map by hostname
            cred_map = {cred['identifier']: cred for cred in cube_creds}

            print(f"\nFound {len(cube_creds)} credential entries in credentials.env")

            for router in routers:
                # Try to find matching credentials by hostname
                creds = cred_map.get(router['hostname'])

                if creds:
                    username = creds['username']
                    password = creds['password']
                    logger.info(f"Found credentials for {router['hostname']} in credentials.env")
                    print(f"  ✓ {router['hostname']}: using credentials from credentials.env")
                else:
                    logger.warning(f"No credentials found for {router['hostname']}, will prompt")
                    print(f"  ⚠ {router['hostname']}: no entry in credentials.env, will prompt at connect")
                    username = input(f"    Username for {router['hostname']}: ").strip()
                    password = getpass.getpass(f"    Password for {router['hostname']}: ")

                devices.append({
                    'device_type': SSH_DEVICE_TYPE,
                    'host': router['ip'],
                    'username': username,
                    'password': password,
                    'port': SSH_PORT,
                    'timeout': SSH_TIMEOUT,
                    'ip': router['ip'],
                    'hostname': router['hostname']
                })
    else:
        # Single credential mode
        logger.info("Using single username/password for all routers")

        # Try to load from [CUBE:default] in credentials.env
        default_creds = creds_loader.get_cube_credentials('default')

        if default_creds and default_creds['username']:
            print("\nFound default credentials in credentials.env")
            if args.default:
                use_stored = "y"
                print("Using stored credentials (--default flag set)")
                logger.info("Using stored credentials (--default flag set)")
            else:
                use_stored = input("Use stored credentials? (y/n) [default: y]: ").strip().lower() or "y"

            if use_stored == "y":
                username = default_creds['username']
                password = default_creds['password']
                if not password:
                    password = getpass.getpass("Enter SSH password: ")
                logger.info("Using stored username from credentials.env")
            else:
                username = input("Enter SSH username: ").strip()
                password = getpass.getpass("Enter SSH password: ")
        else:
            # No stored credentials, prompt user
            print("\nNo default credentials found in credentials.env")
            username = input("Enter SSH username: ").strip()
            password = getpass.getpass("Enter SSH password: ")

        # Apply same credentials to all routers
        for router in routers:
            devices.append({
                'device_type': SSH_DEVICE_TYPE,
                'host': router['ip'],
                'username': username,
                'password': password,
                'port': SSH_PORT,
                'timeout': SSH_TIMEOUT,
                'ip': router['ip'],
                'hostname': router['hostname']
            })

    print("\n" + "="*80)
    print("Executing commands...")
    print("="*80)

    results = []
    for i, device_config in enumerate(devices, 1):
        logger.info(f"Processing router {i}/{len(devices)}: {device_config['hostname']}")
        result = check_router_status(device_config, logger)
        memory_section = extract_memory_section(result['output']) if result['output'] else "N/A"
        free_pct = extract_free_percentage(result['output']) if result['output'] else 0
        results.append({
            'hostname': device_config['hostname'],
            'ip': device_config['ip'],
            'success': result['success'],
            'memory': memory_section,
            'free_pct': free_pct
        })

    print("\n" + "="*80)
    print("Summary")
    print("="*80)
    successful = sum(1 for r in results if r['success'])
    print(f"Successful: {successful}/{len(results)}\n")

    low_memory = [r for r in results if r['success'] and r['free_pct'] < low_memory_threshold]
    normal_memory = [r for r in results if not (r['success'] and r['free_pct'] < low_memory_threshold)]

    for result in low_memory:
        print(f"✓ {result['hostname']} ({result['ip']}) ⚠️ LOW FREE MEMORY")
        print(f"  {result['memory']}")
        print()

    for result in normal_memory:
        status = "✓" if result['success'] else "✗"
        print(f"{status} {result['hostname']} ({result['ip']})")
        if result['success']:
            print(f"  {result['memory']}")
        print()

    logger.info(f"Router Status Check - Completed ({successful}/{len(results)} successful)")

    print("\n" + "="*80)
    if args.default:
        send_email = "y"
        print("Sending summary email (--default flag set)")
        logger.info("Sending summary email (--default flag set)")
    else:
        send_email = input("Send summary email? (y/n): ").strip().lower() or "y"

    if send_email == 'y':
        send_summary_email(results, timestamp, logger, email_cfg, low_memory_threshold)


if __name__ == "__main__":
    main()
