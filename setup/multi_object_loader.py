#!/usr/bin/env python3
"""
Multi-object loader utility for UC automation scripts.
Handles loading and credential management for:
- CUCM and CUC clusters (from clusters.csv)
- CUBE routers (from routers.csv)

Provides centralized credential loading with per-object fallback to defaults.
"""

from pathlib import Path
from csv import DictReader
import json
import sys
import getpass
from setup.env_loader import CredentialsLoader


def validate_cluster_type(cluster_type):
    """Validate cluster_type value. Valid: cucm, cuc (case-insensitive)."""
    valid_types = ['cucm', 'cuc']
    if cluster_type.lower() not in valid_types:
        return False
    return True


def validate_server_type(server_type):
    """Validate server_type value. Valid: publisher, subscriber, em (case-insensitive)."""
    valid_types = ['publisher', 'subscriber', 'em']
    if server_type.lower() not in valid_types:
        return False
    return True


def read_clusters_csv(clusters_file):
    """Read cluster definitions from CSV file (cluster_type, server_type, cluster_name, server, version)."""
    clusters = []
    try:
        with open(clusters_file, 'r', encoding='utf8') as f:
            reader = DictReader(f)
            for row in reader:
                if not row or not row.get('cluster_name', '').strip():
                    continue
                cluster_name = row['cluster_name'].strip()
                server = row.get('server', '').strip()
                version = row.get('version', '').strip()
                cluster_type = row.get('cluster_type', '').strip()
                server_type = row.get('server_type', '').strip()

                if not cluster_name or not server or not version:
                    print(f"Warning: Skipping incomplete cluster row: {row}")
                    continue

                # Validate cluster_type
                if cluster_type and not validate_cluster_type(cluster_type):
                    print(f"Warning: Invalid cluster_type '{cluster_type}' for cluster {cluster_name}. Valid values: cucm, cuc")
                    continue

                # Validate server_type
                if server_type and not validate_server_type(server_type):
                    print(f"Warning: Invalid server_type '{server_type}' for cluster {cluster_name}. Valid values: publisher, subscriber, em")
                    continue

                clusters.append({
                    'name': cluster_name,
                    'server': server,
                    'version': version,
                    'cluster_type': cluster_type.lower() if cluster_type else 'cucm',
                    'server_type': server_type.lower() if server_type else 'publisher'
                })
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"Error reading clusters.csv: {e}")
        return []

    return clusters


def read_routers_csv(routers_file):
    """Read router definitions from CSV file (router_ip, hostname)."""
    routers = []
    try:
        with open(routers_file, 'r', encoding='utf8') as f:
            reader = DictReader(f)
            for row in reader:
                if not row or not row.get('router_ip', '').strip():
                    continue
                router_ip = row['router_ip'].strip()
                hostname = row.get('hostname', '').strip()

                if not router_ip or not hostname:
                    print(f"Warning: Skipping incomplete router row: {row}")
                    continue

                routers.append({
                    'name': hostname,
                    'ip': router_ip
                })
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"Error reading routers.csv: {e}")
        return []

    return routers


def filter_clusters_by_server_type(clusters, service, server_type):
    """
    Filter clusters by cluster_type and server_type.

    Args:
        clusters (list): List of cluster dicts
        service (str): Service type ('CUCM', 'CUC')
        server_type (str): Server type filter ('publisher', 'subscriber', 'cluster', 'em')
                          'cluster' means both publisher and subscriber

    Returns:
        list: Filtered list of cluster dicts
    """
    if not clusters or service.upper() == 'CUBE':
        return clusters

    service = service.lower()
    server_type = server_type.lower() if server_type else 'publisher'

    filtered = []
    for cluster in clusters:
        # Filter by cluster_type
        if cluster.get('cluster_type') != service:
            continue

        # Filter by server_type
        cluster_server_type = cluster.get('server_type', 'publisher')
        if server_type == 'cluster':
            # Include both publisher and subscriber, exclude em
            if cluster_server_type in ['publisher', 'subscriber']:
                filtered.append(cluster)
        elif server_type in ['publisher', 'subscriber', 'em']:
            # Include only matching server_type
            if cluster_server_type == server_type:
                filtered.append(cluster)

    return filtered


def select_object_interactive(objects, object_type='cluster'):
    """Interactively prompt user to select an object from a list."""
    if not objects:
        return None

    print("\n" + "="*60)
    print(f"Available {object_type}s:")
    print("="*60)
    for idx, obj in enumerate(objects, 1):
        if object_type.lower() == 'router':
            print(f"  {idx}. {obj['name']:20} ({obj['ip']})")
        else:
            print(f"  {idx}. {obj['name']:20} ({obj['server']})")
    print(f"  {len(objects) + 1}. {object_type.capitalize()} not in list")

    while True:
        try:
            selection = input(f"\nSelect {object_type} [1-{len(objects) + 1}]: ").strip()
            idx = int(selection) - 1
            if 0 <= idx < len(objects):
                selected = objects[idx]
                if object_type.lower() == 'router':
                    print(f"\nSelected: {selected['name']} ({selected['ip']})")
                else:
                    print(f"\nSelected: {selected['name']} ({selected['server']})")
                return selected
            elif idx == len(objects):
                return None
            else:
                print(f"Invalid selection. Please enter 1-{len(objects) + 1}")
        except ValueError:
            print(f"Invalid input. Please enter 1-{len(objects) + 1}")


def load_credentials(service, object_name, creds_loader=None):
    """
    Load credentials for a service/object.

    Flow:
    1. Prompt user: "Use default credentials?" (y/n)
    2. If yes:
       - Load default credentials
       - If username missing, prompt for it
       - If password missing, prompt for it (showing username if exists)
    3. If no:
       - Prompt for username and password

    Args:
        service (str): Service type ('CUCM', 'CUC', 'CUBE')
        object_name (str): Object name (cluster name, router hostname)
        creds_loader: CredentialsLoader instance (created if None)

    Returns:
        tuple: (username, password)
    """
    if creds_loader is None:
        creds_loader = CredentialsLoader()

    use_default = input(f'  Use default credentials? (y/n) [default: y]: ').strip().lower()
    use_default = use_default in ('', 'y', 'yes')

    if use_default:
        # Try to load default credentials
        if service.upper() == 'CUCM':
            creds = creds_loader.get_cucm_credentials('default')
        elif service.upper() == 'CUC':
            creds = creds_loader.get_cuc_credentials('default')
        elif service.upper() == 'CUBE':
            creds = creds_loader.get_cube_credentials('default')
        else:
            creds = None

        username = creds.get('username', '') if creds else ''
        password = creds.get('password', '') if creds else ''

        # Prompt for missing username
        if not username:
            username = input(f'  Enter username: ')

        # Prompt for missing password (showing username if it exists)
        if not password:
            print(f'  Username: {username}')
            password = getpass.getpass(f'  Enter password: ')

        return username, password
    else:
        # Prompt for credentials
        username = input(f'  Enter username: ')
        password = getpass.getpass(f'  Enter password: ')
        return username, password


def get_object_for_single_operation(basepath, service, server_type=None):
    """
    Load a single cluster/router for single-operation scripts.

    Args:
        basepath (Path): Base path for searching CSV files
        service (str): 'CUCM', 'CUC', or 'CUBE'
        server_type (str): For CUCM/CUC, filter by server type ('publisher', 'subscriber', 'cluster', 'em').
                          'cluster' includes both publisher and subscriber. Ignored for CUBE.

    Returns:
        dict: Object dict with keys: name, server/ip, version (if applicable)
    """
    if service.upper() == 'CUBE':
        csv_file = basepath.parent / '_DATA' / 'routers.csv'
        objects = read_routers_csv(csv_file)
        object_type = 'router'
    else:
        csv_file = basepath.parent / '_DATA' / 'clusters.csv'
        objects = read_clusters_csv(csv_file)
        # Filter by server_type if provided
        if server_type:
            objects = filter_clusters_by_server_type(objects, service, server_type)
        object_type = 'cluster'

    if objects:
        selected = select_object_interactive(objects, object_type)
        if selected:
            return selected

    # Fallback: interactive input
    print(f"\n{object_type.capitalize()}s CSV not found or no objects available.")
    if service.upper() == 'CUBE':
        print("Please provide router information manually:")
        name = input(f"Router hostname (e.g., router-01): ").strip() or "default"
        ip = input(f"IP Address: ").strip()
        if not ip:
            print("Error: IP is required")
            return None
        return {'name': name, 'ip': ip}
    else:
        print("Please provide cluster information manually:")
        name = input(f"{service} Cluster Name (e.g., {service}1): ").strip() or "default"
        server = input(f"IP Address: ").strip()
        version = input(f"{service} Version (e.g., 15.0): ").strip() or "15.0"
        if not server:
            print("Error: IP Address is required")
            return None
        return {'name': name, 'server': server, 'version': version, 'cluster_type': service.lower(), 'server_type': 'publisher'}


def get_objects_for_multi_operation(basepath, service, server_type=None):
    """
    Load all clusters/routers for multi-operation scripts.

    Args:
        basepath (Path): Base path for searching CSV files
        service (str): 'CUCM', 'CUC', or 'CUBE'
        server_type (str): For CUCM/CUC, filter by server type ('publisher', 'subscriber', 'cluster', 'em').
                          'cluster' includes both publisher and subscriber. Ignored for CUBE.

    Returns:
        list: List of object dicts
    """
    if service.upper() == 'CUBE':
        csv_file = basepath.parent / '_DATA' / 'routers.csv'
        objects = read_routers_csv(csv_file)
    else:
        csv_file = basepath.parent / '_DATA' / 'clusters.csv'
        objects = read_clusters_csv(csv_file)
        # Filter by server_type if provided
        if server_type:
            objects = filter_clusters_by_server_type(objects, service, server_type)

    return objects


def load_credentials_for_multi_objects(service, objects, use_same=True):
    """
    Load credentials for multiple objects.

    Args:
        service (str): Service type ('CUCM', 'CUC', 'CUBE')
        objects (list): List of object dicts
        use_same (bool): If True, use same credentials for all; if False, per-object

    Returns:
        dict: Mapping of object_name -> (username, password)
    """
    object_credentials = {}
    creds_loader = CredentialsLoader()

    if use_same:
        # Single credential mode
        print("\n" + "="*80)
        print("Loading Credentials")
        print("="*80)

        use_default = input(f'Use default credentials? (y/n) [default: y]: ').strip().lower()
        use_default = use_default in ('', 'y', 'yes')

        if use_default:
            # Try default credentials
            if service.upper() == 'CUCM':
                creds = creds_loader.get_cucm_credentials('default')
            elif service.upper() == 'CUC':
                creds = creds_loader.get_cuc_credentials('default')
            elif service.upper() == 'CUBE':
                creds = creds_loader.get_cube_credentials('default')
            else:
                creds = None

            username = creds.get('username', '') if creds else ''
            password = creds.get('password', '') if creds else ''

            # Prompt for missing username
            if not username:
                username = input(f'  Enter username: ')

            # Prompt for missing password (showing username if it exists)
            if not password:
                print(f'  Username: {username}')
                password = getpass.getpass(f'  Enter password: ')
        else:
            # Prompt for credentials
            username = input(f'Enter {service} Username: ')
            password = getpass.getpass(f'Enter {service} Password: ')

        # Apply to all objects
        for obj in objects:
            object_credentials[obj['name']] = (username, password)
    else:
        # Per-object credential mode
        print()
        for obj in objects:
            obj_name = obj['name']
            if 'ip' in obj:
                print(f"Router: {obj_name} ({obj['ip']})")
            else:
                print(f"Cluster: {obj_name} ({obj['server']})")

            username, password = load_credentials(service, obj_name, creds_loader)
            object_credentials[obj_name] = (username, password)
            print()

    return object_credentials
