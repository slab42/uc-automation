#!/usr/bin/env python3
"""
Test script for CredentialsLoader.
Demonstrates how to load and use credentials from credentials.env.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.env_loader import CredentialsLoader


def main():
    print("Testing CredentialsLoader")
    print("=" * 80)

    # Initialize loader
    creds_loader = CredentialsLoader()

    # Check if credentials.env exists
    creds_file = Path(__file__).parent.parent / ".env/credentials.env"
    if not creds_file.exists():
        print(f"ERROR: {creds_file} not found")
        print("Copy from .env.EXAMPLE/credentials.env.EXAMPLE to get started")
        return

    print(f"\nLoaded credentials from: {creds_file}")

    # List all available credentials
    all_creds = creds_loader.list_credentials()
    print(f"\nAll credentials found: {len(all_creds)}")
    for cred in all_creds:
        print(f"  - {cred}")

    # Test CUCM credentials
    print("\n" + "=" * 80)
    print("CUCM Credentials:")
    cucm_list = creds_loader.get_cucm_credentials()
    if cucm_list:
        print(f"Found {len(cucm_list)} CUCM cluster(s):")
        for cucm in cucm_list:
            print(f"  - {cucm['identifier']}")
            print(f"    Server: {cucm.get('server', 'N/A')}")
            print(f"    Version: {cucm.get('version', 'N/A')}")
            print(f"    Username: {cucm.get('username', 'N/A')}")
    else:
        print("No CUCM credentials found")

    # Test CUC credentials
    print("\n" + "=" * 80)
    print("CUC Credentials:")
    cuc_list = creds_loader.get_cuc_credentials()
    if cuc_list:
        print(f"Found {len(cuc_list)} CUC cluster(s):")
        for cuc in cuc_list:
            print(f"  - {cuc['identifier']}")
            print(f"    Server: {cuc.get('server', 'N/A')}")
            print(f"    Username: {cuc.get('username', 'N/A')}")
    else:
        print("No CUC credentials found")

    # Test CUBE credentials
    print("\n" + "=" * 80)
    print("CUBE Credentials:")
    cube_list = creds_loader.get_cube_credentials()
    if cube_list:
        print(f"Found {len(cube_list)} CUBE device(s):")
        for cube in cube_list:
            print(f"  - {cube['identifier']}")
            print(f"    Host: {cube.get('host', 'N/A')}")
            print(f"    Hostname: {cube.get('hostname', 'N/A')}")
            print(f"    Username: {cube.get('username', 'N/A')}")
            print(f"    Port: {cube.get('port', 'N/A')}")
    else:
        print("No CUBE credentials found")

    # Test Webex credentials
    print("\n" + "=" * 80)
    print("Webex Credentials:")
    webex_list = creds_loader.get_webex_credentials()
    if webex_list:
        print(f"Found {len(webex_list)} Webex cluster(s):")
        for webex in webex_list:
            print(f"  - {webex['identifier']}")
            print(f"    API Token: {webex.get('api_token', 'N/A')[:10]}...")
    else:
        print("No Webex credentials found")

    print("\n" + "=" * 80)
    print("Test completed successfully!")


if __name__ == "__main__":
    main()
