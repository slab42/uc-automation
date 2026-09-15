#!/usr/bin/env python3
"""
Cisco Router Platform Software Status Checker

Connects to multiple Cisco routers via SSH and executes:
  show platform software status control-processor br

CSV Format (headers optional, searched by name):
  router_ip,hostname
  192.168.1.1,router-01
  192.168.1.2,router-02
"""

import warnings
warnings.filterwarnings('ignore')

import csv
import getpass
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

# Email Configuration
MAIL_SERVER = "mail.slab42.net"
MAIL_PORT = 25
SOURCE_EMAIL = "cube-mem-check@slab42.net"
DESTINATION_EMAIL = "alerts@slab42.net"

# Memory Threshold Configuration
LOW_MEMORY_THRESHOLD = 33  # Alert when free memory is below this percentage

# Add parent directory to path to import from cucm
sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.logger import setup_logger

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
            # Stop after we've captured a reasonable amount (memory table is usually ~5-6 lines)
            if memory_section and len(memory_section) > 1 and line.strip() and not line[0].isspace():
                if 'Memory' not in line:
                    memory_section.pop()
                    break

    return '\n'.join(memory_section) if memory_section else "Memory section not found"


def extract_free_percentage(output):
    """Extract the Free (Pct) value from router output."""
    lines = output.split('\n')

    for line in lines:
        # Look for lines with Free (Pct) data (e.g., "1250232 (32%)")
        if 'RP0' in line or 'RP1' in line:
            parts = line.split()
            # Find all percentages in the line
            percentages = []
            for part in parts:
                if part.endswith('%)') and '(' in part:
                    pct_str = part.strip('()%')
                    try:
                        percentages.append(int(pct_str))
                    except ValueError:
                        continue
            # Free (Pct) is the second percentage (Used, Free, Committed order)
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

            # Search for expected columns (case-insensitive)
            fieldnames_lower = [h.lower() for h in reader.fieldnames]
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


def send_summary_email(results, timestamp, logger):
    """Send a summary email with router check results."""
    try:
        # Build email body
        body = f"Router Memory Status Check - {timestamp}\n"
        body += "=" * 80 + "\n\n"

        successful = sum(1 for r in results if r['success'])
        body += f"Summary: {successful}/{len(results)} routers successful\n\n"

        for result in results:
            status = "✓ SUCCESS" if result['success'] else "✗ FAILED"
            highlight = " ⚠️ LOW FREE MEMORY" if result['success'] and result['free_pct'] < LOW_MEMORY_THRESHOLD else ""
            body += f"{status} - {result['hostname']} ({result['ip']}){highlight}\n"
            if result['success']:
                body += f"  Memory Info: {result['memory']}\n"
            body += "\n"

        # Create MIME message
        msg = MIMEMultipart()
        msg['From'] = SOURCE_EMAIL
        msg['To'] = DESTINATION_EMAIL
        msg['Subject'] = f"Router Memory Status Check - {timestamp}"
        msg.attach(MIMEText(body, 'plain'))

        # Send email
        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
        server.send_message(msg)
        server.quit()

        logger.info(f"Summary email sent to {DESTINATION_EMAIL}")
        print(f"✓ Summary email sent to {DESTINATION_EMAIL}")
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

    # Extract only netmiko-compatible parameters
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
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"logs/{timestamp}-check_router_status.log"
    logger = setup_logger(log_file)

    logger.info("Router Status Check - Started")

    # Prompt for CSV file
    csv_input = input("Enter path to CSV file (routers): ").strip()
    if not csv_input:
        csv_input = "routers.csv"

    # Read routers from CSV
    routers = read_csv_routers(csv_input)
    if not routers:
        logger.error("No routers found in CSV file")
        return

    logger.info(f"Found {len(routers)} router(s) to check")
    print(f"\nFound {len(routers)} router(s):")
    for r in routers:
        print(f"  - {r['hostname']} ({r['ip']})")

    # Prompt for credentials
    print("\n" + "="*80)
    username = input("Enter SSH username: ").strip()
    password = getpass.getpass("Enter SSH password: ")

    # Build device configurations
    devices = []
    for router in routers:
        devices.append({
            'device_type': 'cisco_ios',
            'host': router['ip'],
            'username': username,
            'password': password,
            'port': 22,
            'timeout': 15,
            'ip': router['ip'],
            'hostname': router['hostname']
        })

    # Connect to each router and run command
    print("\n" + "="*80)
    print("Executing commands...")
    print("="*80)

    results = []
    for i, device_config in enumerate(devices, 1):
        logger.info(f"Processing router {i}/{len(devices)}: {routers[i-1]['hostname']}")
        result = check_router_status(device_config, logger)
        memory_section = extract_memory_section(result['output']) if result['output'] else "N/A"
        free_pct = extract_free_percentage(result['output']) if result['output'] else 0
        results.append({
            'hostname': routers[i-1]['hostname'],
            'ip': routers[i-1]['ip'],
            'success': result['success'],
            'memory': memory_section,
            'free_pct': free_pct
        })

    # Summary
    print("\n" + "="*80)
    print("Summary")
    print("="*80)
    successful = sum(1 for r in results if r['success'])
    print(f"Successful: {successful}/{len(results)}\n")

    # Separate low memory routers from normal ones
    low_memory = [r for r in results if r['success'] and r['free_pct'] < LOW_MEMORY_THRESHOLD]
    normal_memory = [r for r in results if not (r['success'] and r['free_pct'] < LOW_MEMORY_THRESHOLD)]

    # Print low memory routers first
    for result in low_memory:
        status = "✓"
        print(f"{status} {result['hostname']} ({result['ip']}) ⚠️ LOW FREE MEMORY")
        print(f"  {result['memory']}")
        print()

    # Print normal routers
    for result in normal_memory:
        status = "✓" if result['success'] else "✗"
        print(f"{status} {result['hostname']} ({result['ip']})")
        if result['success']:
            print(f"  {result['memory']}")
        print()

    logger.info(f"Router Status Check - Completed ({successful}/{len(results)} successful)")

    # Send summary email
    print("\n" + "="*80)
    send_email = input("Send summary email? (y/n): ").strip().lower()
    if send_email == 'y':
        send_summary_email(results, timestamp, logger)


if __name__ == "__main__":
    main()
