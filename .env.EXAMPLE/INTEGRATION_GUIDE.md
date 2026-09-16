# Credentials Integration Guide

This guide shows how to integrate the new `CredentialsLoader` into existing scripts and create new ones.

## Quick Start

### Setup

1. Copy example credentials file:
   ```bash
   cp .env.EXAMPLE/credentials.env.EXAMPLE .env/credentials.env
   ```

2. Edit `.env/credentials.env` and add your clusters/devices:
   ```ini
   [CUCM:production]
   server=192.168.10.100
   username=axl_user
   password=
   version=15.0

   [CUBE:router1]
   host=192.168.20.2
   hostname=router-01
   username=admin
   password=
   port=22
   device_type=cisco_ios
   ```

3. Test the loader:
   ```bash
   python3 setup/test_credentials_loader.py
   ```

## Script Integration Examples

### CUCM Script Template

Before (using cucm-info.json):
```python
import json

def setup():
    config_path = input("Path to config file: ").strip() or "cucm-info.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config
```

After (using CredentialsLoader):
```python
from setup.env_loader import CredentialsLoader

def setup():
    creds_loader = CredentialsLoader()
    clusters = creds_loader.list_credentials('CUCM')
    
    if not clusters:
        print("ERROR: No CUCM credentials found in .env/credentials.env")
        return None
    
    if len(clusters) == 1:
        cluster_name = clusters[0].split(':')[1]
    else:
        print("Available CUCM clusters:")
        for i, cluster in enumerate(clusters, 1):
            print(f"  {i}. {cluster.split(':')[1]}")
        choice = input("Select cluster number: ").strip()
        cluster_name = clusters[int(choice) - 1].split(':')[1]
    
    return creds_loader.get_cucm_credentials(cluster_name)
```

### CUBE Script Template

Before (using routers.csv and prompting for credentials):
```python
import csv
import getpass

def get_router_list(csv_path):
    routers = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            routers.append({
                'ip': row['router_ip'],
                'hostname': row['hostname']
            })
    return routers

def main():
    routers = get_router_list('routers.csv')
    username = input("Enter SSH username: ").strip()
    password = getpass.getpass("Enter SSH password: ")
    
    for router in routers:
        device = {
            'device_type': 'cisco_ios',
            'host': router['ip'],
            'username': username,
            'password': password,
            'port': 22
        }
        connect_and_execute(device)
```

After (using CredentialsLoader):
```python
from setup.env_loader import CredentialsLoader
from netmiko import ConnectHandler

def main():
    creds_loader = CredentialsLoader()
    devices = creds_loader.get_cube_credentials()
    
    if not devices:
        print("ERROR: No CUBE credentials found in .env/credentials.env")
        return
    
    print(f"Found {len(devices)} device(s):")
    for device in devices:
        print(f"  - {device['identifier']}: {device['hostname']}")
    
    for device_creds in devices:
        # Password prompting happens automatically if blank in credentials.env
        with ConnectHandler(**device_creds) as net_connect:
            output = net_connect.send_command("show version")
            print(output)
```

### Multi-Cluster CUCM Script

```python
from setup.env_loader import CredentialsLoader
from cucm.ucmAPI import AXL

def main():
    creds_loader = CredentialsLoader()
    cucm_clusters = creds_loader.get_cucm_credentials()
    
    if not cucm_clusters:
        print("No CUCM clusters configured")
        return
    
    # Process all clusters
    for cluster in cucm_clusters:
        print(f"\nProcessing cluster: {cluster['identifier']}")
        
        # Get password if needed
        if not cluster['password']:
            cluster['password'] = getpass.getpass(f"Password for {cluster['identifier']}: ")
        
        # Create AXL client
        axl = AXL(
            username=cluster['username'],
            password=cluster['password'],
            cucm=cluster['server'],
            wsdl=f"schema/{cluster['version']}/AXLAPI.wsdl",
            cucm_version=cluster['version']
        )
        
        # Do work...
        result = axl.add_advertised_patterns(...)
        print(result)
```

### Webex Script Template

```python
from setup.env_loader import CredentialsLoader
import requests

def main():
    creds_loader = CredentialsLoader()
    webex = creds_loader.get_webex_credentials('main')
    
    if not webex:
        print("Webex credentials not found")
        return
    
    headers = {
        'Authorization': f"Bearer {webex['api_token']}",
        'Content-Type': 'application/json'
    }
    
    response = requests.get(
        'https://webexapis.com/v1/locations',
        headers=headers
    )
    
    locations = response.json()
    for loc in locations['items']:
        print(f"Location: {loc['name']}")
```

## Migration Path

### Step 1: Add credentials to credentials.env

For each script, add corresponding entries:

```ini
# For CUCM scripts
[CUCM:cluster_name]
server=...
username=...
password=
version=...

# For CUBE scripts
[CUBE:router_name]
host=...
hostname=...
username=...
password=...
port=22
device_type=cisco_ios
```

### Step 2: Update imports

Add at top of script:
```python
from setup.env_loader import CredentialsLoader
```

### Step 3: Update credential loading

Replace manual config loading with:
```python
creds_loader = CredentialsLoader()
creds = creds_loader.get_cucm_credentials('cluster_name')
# or
devices = creds_loader.get_cube_credentials()
```

### Step 4: Test

```bash
# For CUCM scripts
python3 script_name.py

# Should work with credentials from .env/credentials.env
```

## Advanced Usage

### Using environment variables for passwords

```python
import os
from setup.env_loader import CredentialsLoader

creds_loader = CredentialsLoader()
creds = creds_loader.get_cucm_credentials('production')

# Override password from environment variable
if 'CUCM_PASSWORD' in os.environ:
    creds['password'] = os.environ['CUCM_PASSWORD']
```

### Custom credential paths

```python
# Use custom credentials file location
creds_loader = CredentialsLoader(creds_path=".env/custom_creds.env")
```

### Credentials validation

```python
def validate_credentials(creds, required_fields):
    """Ensure all required fields are present."""
    missing = [f for f in required_fields if not creds.get(f)]
    if missing:
        print(f"ERROR: Missing fields: {', '.join(missing)}")
        return False
    return True

# Usage
creds = creds_loader.get_cucm_credentials('production')
if validate_credentials(creds, ['server', 'username', 'password', 'version']):
    # Use credentials
    ...
```

## Troubleshooting

### "No credentials found"

1. Check file exists:
   ```bash
   ls -la .env/credentials.env
   ```

2. Check for proper section headers:
   ```bash
   grep "^\[" .env/credentials.env
   ```

3. Verify no syntax errors:
   ```bash
   python3 setup/test_credentials_loader.py
   ```

### Password prompting not working

- Ensure password field is blank (not empty lines):
  ```ini
  password=
  ```
  Not:
  ```ini
  password =
  ```

### Wrong credentials loaded

- Use identifier matching:
  ```python
  # This looks for section [CUCM:production]
  creds = creds_loader.get_cucm_credentials('production')
  ```

- Check actual section names:
  ```python
  clusters = creds_loader.list_credentials('CUCM')
  print(clusters)  # Shows actual [CUCM:names]
  ```

## Password Security

### Development/Testing (not recommended for production)

Store password in credentials.env:
```ini
[CUCM:test]
password=test_password
```

### Production (recommended)

Leave password blank to prompt:
```ini
[CUCM:prod]
password=
```

Or use environment variables:
```bash
# In shell or CI/CD
export CUCM_PROD_PASSWORD="actual_password"
```

Then in script:
```python
import os
creds = creds_loader.get_cucm_credentials('prod')
if not creds['password'] and 'CUCM_PROD_PASSWORD' in os.environ:
    creds['password'] = os.environ['CUCM_PROD_PASSWORD']
```
