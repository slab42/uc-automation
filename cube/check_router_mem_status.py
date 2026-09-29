#!/usr/bin/env python3
# TITLE: Router Memory Status

"""
Cisco Router Platform Software Status Checker

Connects to one or more Cisco routers via SSH and executes:
  show platform software status control-processor br

Usage:
    python3 check_router_mem_status.py [-d]

    -d, --default: Non-interactive mode for scheduled runs. Uses all routers
        from _DATA/routers.csv, [CUBE:default] credentials from credentials.env
        (falls back to a password prompt if none is stored), skips the
        customer variable validation prompt, and sends the summary email
        without asking.

The script is interactive and will prompt for:
    CUBE Router(s): select from routers.csv or provide manually
    Use multiple routers?: (Y/n): use all routers found in routers.csv,
        or select a single router
    Credentials: checks stored credentials in credentials.env
    Use same credentials for all routers?: (Y/n) (multi-router mode only)
    Send summary email?: (Y/n)

Customer Variables - Imported from .var/check_router_mem_status.var
  low_memory_threshold - Free memory percentage threshold for alerts (default: 33)

Router list from CSV file (_DATA/routers.csv):
  router_ip,hostname
  192.168.1.1,router-01
  192.168.1.2,router-02

Credentials from .env/credentials.env:
    [CUBE:default] - Single credential set for all routers
    [CUBE:<hostname>] - Per-router credentials matched by hostname

See .env.EXAMPLE/CREDENTIALS_ENV_README.md for credentials.env setup.

Output: Summary printed to console; optional email sent via customer_env.json
    email settings.
Logs: ../_logs/<timestamp>-check-router-mem-status.log
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import warnings
warnings.filterwarnings('ignore')

import argparse
import getpass
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.env_loader import EnvironmentConfig, CredentialsLoader
from setup.var_loader import load_customer_variables
from setup.multi_object_loader import (
    get_object_for_single_operation,
    load_credentials,
    get_objects_for_multi_operation,
    load_credentials_for_multi_objects
)

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except ImportError:
    print("ERROR: netmiko not installed. Install with: pip install netmiko")
    sys.exit(1)

# SSH connection settings
SSH_DEVICE_TYPE = 'cisco_ios'
SSH_PORT = 22
SSH_TIMEOUT = 15


def build_device(router, username, password):
    """Build a netmiko device dict from a router dict and credentials.

    Args:
        router (dict): Router dict with 'name' (hostname) and 'ip' keys.
        username (str): SSH username.
        password (str): SSH password.

    Returns:
        dict: netmiko connection params plus 'ip'/'hostname' for display.
    """
    return {
        'device_type': SSH_DEVICE_TYPE,
        'host': router['ip'],
        'username': username,
        'password': password,
        'port': SSH_PORT,
        'timeout': SSH_TIMEOUT,
        'ip': router['ip'],
        'hostname': router['name']
    }


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


def send_summary_email(results, timestamp, logger, email_cfg, low_memory_threshold):
    """Send a summary email with router check results."""
    try:
        body = f"Router Memory Status Check - {timestamp}\n"
        body += "=" * 80 + "\n\n"

        successful = sum(1 for r in results if r['success'])
        body += f"Summary: {successful}/{len(results)} routers successful\n\n"

        for result in results:
            status = "✓ SUCCESS" if result['success'] else "✗ FAILED"
            highlight = " ⚠ LOW FREE MEMORY" if result['success'] and result['free_pct'] < low_memory_threshold else ""
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


def run_checks(devices, logger):
    """Run the memory status check on each device and collect results.

    Args:
        devices (list): List of netmiko device dicts (from build_device).
        logger: logger instance.

    Returns:
        list: Result dicts with hostname, ip, success, memory, free_pct.
    """
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
    return results


def print_summary(results, low_memory_threshold):
    """Print a console summary of results, highlighting low-memory routers."""
    print("\n" + "="*80)
    print("Summary")
    print("="*80)
    successful = sum(1 for r in results if r['success'])
    print(f"Successful: {successful}/{len(results)}\n")

    low_memory = [r for r in results if r['success'] and r['free_pct'] < low_memory_threshold]
    normal_memory = [r for r in results if not (r['success'] and r['free_pct'] < low_memory_threshold)]

    for result in low_memory:
        print(f"✓ {result['hostname']} ({result['ip']}) ⚠ LOW FREE MEMORY")
        print(f"  {result['memory']}")
        print()

    for result in normal_memory:
        status = "✓" if result['success'] else "✗"
        print(f"{status} {result['hostname']} ({result['ip']})")
        if result['success']:
            print(f"  {result['memory']}")
        print()

    return successful


def main():
    """Entry point: load routers/credentials, run memory checks, report/email results."""
    parser = argparse.ArgumentParser(description='Check Cisco router memory status')
    parser.add_argument('-d', '--default', action='store_true', help='Accept defaults for all prompts without user interaction')
    args = parser.parse_args()

    basepath = Path.cwd()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-check-router-mem-status.log"
    logger = setup_logger(log_file)
    logger.info("Router Memory Status - Started")

    # Load customer variables from .var file
    customer_vars = load_customer_variables(__file__, logger, skip_prompts=args.default)
    low_memory_threshold = int(customer_vars.get('low_memory_threshold', 33)) if customer_vars else 33

    env_config = EnvironmentConfig()
    email_cfg = env_config.get_email_config()

    devices = []

    if args.default:
        logger.info("Default mode: using all routers from routers.csv")
        routers = get_objects_for_multi_operation(basepath, 'CUBE')
        if not routers:
            logger.error("No routers found in _DATA/routers.csv")
            print("ERROR: No routers found in _DATA/routers.csv")
            return

        creds_loader = CredentialsLoader()
        default_creds = creds_loader.get_cube_credentials('default')
        if default_creds and default_creds.get('username'):
            username = default_creds['username']
            password = default_creds.get('password', '')
            if not password:
                logger.warning("No stored password for [CUBE:default]; prompting (no other option in --default mode)")
                password = getpass.getpass("Enter SSH password: ")
        else:
            logger.warning("No [CUBE:default] credentials found; prompting (no other option in --default mode)")
            username = input("Enter SSH username: ").strip()
            password = getpass.getpass("Enter SSH password: ")

        for router in routers:
            devices.append(build_device(router, username, password))
    else:
        routers = get_objects_for_multi_operation(basepath, 'CUBE')
        if routers:
            use_multiple = prompt_yes_no(f'{len(routers)} routers found. Use multiple routers?', default=True)
        else:
            use_multiple = False

        if use_multiple:
            use_same = prompt_yes_no('Use same credentials for all routers?', default=True)
            router_credentials = load_credentials_for_multi_objects('CUBE', routers, use_same=use_same)
            for router in routers:
                username, password = router_credentials[router['name']]
                devices.append(build_device(router, username, password))
        else:
            router = get_object_for_single_operation(basepath, 'CUBE')
            if not router:
                print("Error: Unable to load router information")
                sys.exit(1)
            username, password = load_credentials('CUBE', router['name'])
            devices.append(build_device(router, username, password))

    print("\n" + "="*80)
    print("Executing commands...")
    print("="*80)

    results = run_checks(devices, logger)
    successful = print_summary(results, low_memory_threshold)

    logger.info(f"Router Memory Status - Completed ({successful}/{len(results)} successful)")

    if args.default:
        send_email = True
        print("Sending summary email (--default flag set)")
        logger.info("Sending summary email (--default flag set)")
    else:
        print("\n" + "="*80)
        send_email = prompt_yes_no("Send summary email?", default=True)

    if send_email:
        send_summary_email(results, timestamp, logger, email_cfg, low_memory_threshold)


if __name__ == "__main__":
    main()
