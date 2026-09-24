#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Test script to find which table CSSs are stored in
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
    print("Finding CSS Table Name")
    print("="*80 + "\n")

    # Try different possible table names
    possible_css_tables = [
        'css',
        'callingSearchSpace',
        'callingsearchspace',
        'cssinfo',
        'cssconfig',
        'cssdata',
        'css_config',
        'calling_search_space',
        'CallingSearchSpace',
    ]

    found_css_table = None

    for table_name in possible_css_tables:
        print(f"Testing table: {table_name}...")
        query = f"SELECT pkid, name FROM {table_name} LIMIT 1"
        query_result = axl.execute_sql_query(query)

        if query_result.get('success'):
            print(f"  ✓ SUCCESS! Table '{table_name}' exists and contains data")
            print(f"    Columns: {list(query_result.get('response', [{}])[0].keys())}")
            found_css_table = table_name

            # Get all CSS names
            query2 = f"SELECT name FROM {table_name} ORDER BY name"
            query_result2 = axl.execute_sql_query(query2)
            if query_result2.get('success'):
                css_names = []
                for row in query_result2.get('response', []):
                    if isinstance(row, dict) and 'name' in row:
                        css_names.append(row['name'])
                print(f"    CSSs in table ({len(css_names)}): {css_names[:5]}")
            break
        else:
            error = query_result.get('error', '')
            if 'not in the database' in error:
                print(f"  ✗ Table not found")
            else:
                print(f"  ? Error: {error[:60]}")

    if found_css_table:
        print(f"\n✓ Found CSS table: {found_css_table}")
    else:
        print(f"\n✗ Could not find CSS table. Tried: {possible_css_tables}")

    print("\n" + "="*80)
