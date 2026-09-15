#!/usr/bin/env python3
"""
Cisco Router Config Template Comparator

Compares router running configs to a template, focusing on voice sections.
Connects via SSH and generates HTML reports for each router.

CSV Format (headers optional, searched by name):
  router_ip,hostname
  192.168.1.1,router-01
  192.168.1.2,router-02

Template Format:
  Plain text file with voice configuration sections (e.g., voice class, voice-port, dial-peer).
  Only sections present in template are checked; missing sections in router config are ignored.
"""

import warnings
warnings.filterwarnings('ignore')

import csv
import getpass
import sys
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from html import escape

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except ImportError:
    print("ERROR: netmiko not installed. Install with: pip install netmiko")
    sys.exit(1)

from cucm.general import findFiles
from setup.on_prem.logger import setup_logger


class ConfigParser:
    """Parse Cisco router configs into hierarchical sections."""

    @staticmethod
    def parse_sections(config_text):
        """Parse config into sections based on top-level commands."""
        sections = {}
        current_section = None
        current_lines = []

        for line in config_text.split('\n'):
            stripped = line.strip()

            if not stripped or stripped.startswith('!'):
                continue

            if line and not line[0].isspace():
                if current_section:
                    sections[current_section] = current_lines
                current_section = stripped
                current_lines = [stripped]
            elif current_section:
                current_lines.append(line.rstrip())

        if current_section:
            sections[current_section] = current_lines

        return sections

    @staticmethod
    def extract_voice_sections(config_text):
        """Extract only voice-related sections from config."""
        voice_keywords = [
            'voice', 'dial-peer', 'call-manager', 'ephone',
            'telephony-service', 'gateway', 'h323', 'mgcp',
            'sccp', 'sip', 'isdn', 'primary-rate', 'bri',
            'ds0', 'voice-port', 'connection', 'pots',
            'fax', 'codec', 'class provider'
        ]

        sections = ConfigParser.parse_sections(config_text)
        voice_sections = {}

        for section_name, lines in sections.items():
            section_lower = section_name.lower()
            if any(keyword in section_lower for keyword in voice_keywords):
                voice_sections[section_name] = lines

        return voice_sections

    @staticmethod
    def normalize_lines(lines):
        """Normalize lines for comparison (strip trailing whitespace)."""
        return [line.rstrip() for line in lines if line.strip()]


class ConfigComparator:
    """Compare template config to router config."""

    def __init__(self, template_sections):
        self.template_sections = template_sections

    def compare(self, router_sections):
        """Compare router config to template. Returns dict with variances."""
        results = {
            'missing_sections': [],
            'extra_sections': [],
            'section_diffs': {}
        }

        for template_section in self.template_sections:
            if template_section not in router_sections:
                results['missing_sections'].append(template_section)
            else:
                template_lines = ConfigParser.normalize_lines(
                    self.template_sections[template_section]
                )
                router_lines = ConfigParser.normalize_lines(
                    router_sections[template_section]
                )

                if template_lines != router_lines:
                    diff = self._compute_diff(template_lines, router_lines)
                    results['section_diffs'][template_section] = diff

        for router_section in router_sections:
            if router_section not in self.template_sections:
                results['extra_sections'].append(router_section)

        return results

    @staticmethod
    def _compute_diff(template_lines, router_lines):
        """Compute line-by-line diff between template and router config."""
        sm = SequenceMatcher(None, template_lines, router_lines)
        diff = {
            'template_only': [],
            'router_only': [],
            'shared': []
        }

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'delete':
                diff['template_only'].extend(template_lines[i1:i2])
            elif tag == 'insert':
                diff['router_only'].extend(router_lines[j1:j2])
            elif tag == 'equal':
                diff['shared'].extend(template_lines[i1:i2])

        return diff


def read_template_file(template_path):
    """Read and parse template config file."""
    try:
        with open(template_path, 'r') as f:
            config_text = f.read()
        return ConfigParser.extract_voice_sections(config_text)
    except FileNotFoundError:
        print(f"ERROR: Template file not found: {template_path}")
        return None
    except Exception as e:
        print(f"ERROR: Failed to read template: {e}")
        return None


def read_csv_routers(csv_path):
    """Read router list from CSV file."""
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


def get_running_config(device_config, logger):
    """Connect to router and get running config via SSH."""
    router_ip = device_config['ip']
    hostname = device_config['hostname']

    logger.info(f"Connecting to {hostname} ({router_ip})...")

    netmiko_params = {k: v for k, v in device_config.items() if k not in ['ip', 'hostname']}

    try:
        with ConnectHandler(**netmiko_params) as net_connect:
            logger.info(f"Connected to {hostname}")
            output = net_connect.send_command("show running-config")
            logger.info(f"Retrieved config from {hostname}")
            return {'success': True, 'output': output}
    except NetmikoAuthenticationException as e:
        error_msg = f"Authentication failed for {hostname}: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except NetmikoTimeoutException as e:
        error_msg = f"Connection timeout for {hostname}: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Failed to connect to {hostname}: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def generate_html_report(hostname, template_sections, comparison_result, output_file):
    """Generate HTML report for config comparison."""
    has_variances = (
        comparison_result['missing_sections'] or
        comparison_result['extra_sections'] or
        comparison_result['section_diffs']
    )

    status_color = '#dc3545' if has_variances else '#28a745'
    status_text = 'VARIANCES FOUND' if has_variances else 'COMPLIANT'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Config Comparison Report - {escape(hostname)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .header {{ background-color: {status_color}; color: white; padding: 20px; border-radius: 5px; }}
        .header h1 {{ margin: 0; }}
        .status {{ font-size: 24px; font-weight: bold; }}
        .timestamp {{ font-size: 12px; margin-top: 10px; }}
        .section {{ background-color: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .section-title {{ background-color: #007bff; color: white; padding: 10px; border-radius: 3px; font-weight: bold; }}
        .variance-type {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 10px; margin: 10px 0; border-radius: 3px; }}
        .missing {{ background-color: #f8d7da; border-left: 4px solid #dc3545; }}
        .extra {{ background-color: #d1ecf1; border-left: 4px solid #17a2b8; }}
        .compliant {{ background-color: #d4edda; border-left: 4px solid #28a745; }}
        .code {{ background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 3px; padding: 10px; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; }}
        .line {{ margin: 3px 0; }}
        .template-only {{ color: #dc3545; }}
        .router-only {{ color: #17a2b8; }}
        .shared {{ color: #28a745; }}
        .label {{ font-weight: bold; font-size: 12px; text-transform: uppercase; }}
        .summary {{ background-color: #e7f3ff; border-left: 4px solid #2196F3; padding: 15px; border-radius: 3px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Router Configuration Comparison Report</h1>
        <div class="status">{status_text}</div>
        <div>Router: {escape(hostname)}</div>
        <div class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>

    <div class="section">
        <div class="summary">
            <div><strong>Template Sections Checked:</strong> {len(template_sections)}</div>
            <div><strong>Missing Sections:</strong> {len(comparison_result['missing_sections'])}</div>
            <div><strong>Extra Sections:</strong> {len(comparison_result['extra_sections'])}</div>
            <div><strong>Sections with Differences:</strong> {len(comparison_result['section_diffs'])}</div>
        </div>
    </div>
"""

    if comparison_result['missing_sections']:
        html += '<div class="section">'
        html += '<div class="section-title">❌ Missing Sections (in template but not in router config)</div>'
        for section in sorted(comparison_result['missing_sections']):
            html += f'<div class="variance-type missing">{escape(section)}</div>'
        html += '</div>'

    if comparison_result['extra_sections']:
        html += '<div class="section">'
        html += '<div class="section-title">ℹ️ Extra Sections (in router config but not in template)</div>'
        for section in sorted(comparison_result['extra_sections']):
            html += f'<div class="variance-type extra">{escape(section)}</div>'
        html += '</div>'

    if comparison_result['section_diffs']:
        for section_name in sorted(comparison_result['section_diffs'].keys()):
            diff = comparison_result['section_diffs'][section_name]
            html += '<div class="section">'
            html += f'<div class="section-title">📝 {escape(section_name)}</div>'

            html += '<div style="margin-top: 10px;">'

            if diff['template_only']:
                html += '<div class="variance-type missing"><span class="label">In Template Only (Missing from Router)</span>'
                html += '<div class="code">'
                for line in diff['template_only']:
                    html += f'<div class="line template-only">- {escape(line)}</div>'
                html += '</div></div>'

            if diff['router_only']:
                html += '<div class="variance-type extra"><span class="label">In Router Only (Extra in Router)</span>'
                html += '<div class="code">'
                for line in diff['router_only']:
                    html += f'<div class="line router-only">+ {escape(line)}</div>'
                html += '</div></div>'

            html += '</div></div>'

    if not has_variances:
        html += '<div class="section"><div class="variance-type compliant"><strong>✓ Configuration is compliant with template</strong></div></div>'

    html += """
</body>
</html>
"""

    try:
        with open(output_file, 'w') as f:
            f.write(html)
        return True
    except Exception as e:
        print(f"ERROR: Failed to write HTML report: {e}")
        return False


def process_single_router(device_config, template_sections, logger):
    """Process a single router comparison."""
    hostname = device_config['hostname']

    print(f"\n{'='*80}")
    print(f"Router: {hostname} ({device_config['ip']})")
    print(f"{'='*80}")

    result = get_running_config(device_config, logger)
    if not result['success']:
        print(f"ERROR: {result['error']}")
        return {'success': False}

    logger.info(f"Parsing config for {hostname}")
    router_sections = ConfigParser.extract_voice_sections(result['output'])

    logger.info(f"Comparing config for {hostname}")
    comparator = ConfigComparator(template_sections)
    comparison_result = comparator.compare(router_sections)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"reports/{timestamp}-{hostname}_comparison.html"

    Path("reports").mkdir(exist_ok=True)

    if generate_html_report(hostname, template_sections, comparison_result, output_file):
        logger.info(f"Report generated: {output_file}")
        print(f"✓ Report saved: {output_file}")
        return {'success': True, 'file': output_file, 'result': comparison_result}
    else:
        logger.error(f"Failed to generate report for {hostname}")
        return {'success': False}


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"logs/{timestamp}-compare_router_config.log"
    logger = setup_logger(log_file)

    logger.info("Router Config Comparison - Started")

    print("="*80)
    print("Router Configuration Template Comparator")
    print("="*80)

    template_path = input("\nEnter path to template config file: ").strip()
    if not template_path:
        logger.error("No template file provided")
        print("ERROR: Template file path required")
        return

    template_sections = read_template_file(template_path)
    if not template_sections:
        logger.error(f"Failed to load template: {template_path}")
        return

    logger.info(f"Loaded template with {len(template_sections)} voice sections")
    print(f"✓ Template loaded with {len(template_sections)} voice sections")

    mode = input("\nSingle router or CSV mode? (s/c) [default: c]: ").strip().lower()
    if mode == 's':
        hostname = input("Enter router hostname: ").strip()
        router_ip = input("Enter router IP address: ").strip()

        username = input("Enter SSH username: ").strip()
        password = getpass.getpass("Enter SSH password: ")

        device = {
            'device_type': 'cisco_ios',
            'host': router_ip,
            'username': username,
            'password': password,
            'port': 22,
            'timeout': 15,
            'ip': router_ip,
            'hostname': hostname
        }

        result = process_single_router(device, template_sections, logger)
        if result['success']:
            logger.info("Single router comparison completed successfully")
        else:
            logger.error("Single router comparison failed")
    else:
        csv_input = input("Enter path to CSV file [default: routers.csv]: ").strip()
        if not csv_input:
            csv_input = "routers.csv"

        routers = read_csv_routers(csv_input)
        if not routers:
            logger.error("No routers found in CSV")
            return

        logger.info(f"Found {len(routers)} router(s) from CSV")
        print(f"\n✓ Found {len(routers)} router(s):")
        for r in routers:
            print(f"  - {r['hostname']} ({r['ip']})")

        username = input("\nEnter SSH username: ").strip()
        password = getpass.getpass("Enter SSH password: ")

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

        print("\n" + "="*80)
        print("Processing routers...")
        print("="*80)

        results = []
        for i, device in enumerate(devices, 1):
            logger.info(f"Processing router {i}/{len(devices)}")
            result = process_single_router(device, template_sections, logger)
            results.append(result)

        print("\n" + "="*80)
        print("Summary")
        print("="*80)
        successful = sum(1 for r in results if r['success'])
        print(f"Completed: {successful}/{len(results)} successful\n")

        for result in results:
            if result['success']:
                has_variances = (
                    result['result']['missing_sections'] or
                    result['result']['extra_sections'] or
                    result['result']['section_diffs']
                )
                status = "✗ VARIANCES" if has_variances else "✓ COMPLIANT"
                print(f"{status}: {result['file']}")

        logger.info(f"Router Config Comparison - Completed ({successful}/{len(results)} successful)")


if __name__ == "__main__":
    main()
