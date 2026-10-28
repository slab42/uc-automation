#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Test script to inspect CUCM database schema for CSS references
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import urllib3
from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from ucmAPI import AXL

if __name__ == '__main__':
    basepath = Path.cwd()
    script_dir = Path(__file__).parent
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
    if not cluster:
        print("Error: Unable to load cluster information")
        sys.exit(1)

    username, password = load_credentials('CUCM', cluster['name'])
    server = cluster['server']
    version = cluster['version']

    wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
    wsdl = wsdl_dir.absolute().as_uri()
    axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

    print("\n" + "="*80)
    print("CUCM Database Schema Inspection")
    print("="*80 + "\n")

    # Check device table columns - raw query
    print("Device table schema inspection:")
    query_result = axl.execute_sql_query("SELECT * FROM device LIMIT 1")
    print(f"Query success: {query_result.get('success')}")
    print(f"Query error: {query_result.get('error')}")
    resp = query_result.get('response', [])
    print(f"Response type: {type(resp)}, length: {len(resp)}")
    if resp:
        print(f"First few items: {resp[:5]}")
        # Extract column names from the response
        columns = []
        for item in resp:
            if isinstance(item, dict):
                columns.extend(item.keys())
        if columns:
            print(f"Extracted columns: {set(columns)}")
            css_related = [c for c in set(columns) if 'css' in c.lower() or 'call' in c.lower()]
            if css_related:
                print(f"CSS-related columns: {css_related}")
    print()

    # Check numplan table columns - raw query
    print("Numplan table schema inspection:")
    query_result = axl.execute_sql_query("SELECT * FROM numplan LIMIT 1")
    print(f"Query success: {query_result.get('success')}")
    print(f"Query error: {query_result.get('error')}")
    resp = query_result.get('response', [])
    print(f"Response type: {type(resp)}, length: {len(resp)}")
    if resp:
        print(f"First few items: {resp[:5]}")
        # Extract column names from the response
        columns = []
        for item in resp:
            if isinstance(item, dict):
                columns.extend(item.keys())
        if columns:
            print(f"Extracted columns: {set(columns)}")
            css_related = [c for c in set(columns) if 'css' in c.lower() or 'call' in c.lower()]
            if css_related:
                print(f"CSS-related columns: {css_related}")
    print()

    # Check for join tables
    print("Looking for potential CSS join tables:")
    join_table_names = ['devicecss', 'device_css', 'cssmember_device', 'device_cssmember',
                        'devicesubscribecss', 'device_subscribe_css']
    for table in join_table_names:
        result = axl.get_table_info(table)
        if result.get('success'):
            print(f"  ✓ Found table: {table}")
            if result.get('columns'):
                for col in result.get('columns', []):
                    print(f"      - {col}")
        else:
            if 'not in the database' not in result.get('error', ''):
                print(f"  ? {table}: {result.get('error')}")

    print("\n" + "="*80)
    print("End of schema inspection")
    print("="*80 + "\n")
