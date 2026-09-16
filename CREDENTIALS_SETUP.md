# Credentials Configuration Setup

This document provides step-by-step instructions to set up and use the centralized credentials system for UC automation.

## Overview

The UC automation project now uses a centralized `credentials.env` file to manage credentials for all services:
- **CUCM** (Cisco Unified Communications Manager)
- **CUC** (Cisco Unity Connection)
- **CUBE** (Cisco Unified Border Element / Routers)
- **Webex** (Calling and Admin APIs)

This replaces the need for individual credential files (like `cucm-info.json`) and interactive password prompts scattered across different scripts.

## Setup Instructions

### Step 1: Copy the Example Credentials File

```bash
cd /path/to/uc-automation
cp .env.EXAMPLE/credentials.env.EXAMPLE .env/credentials.env
```

### Step 2: Edit credentials.env

Open `.env/credentials.env` in your editor and add your clusters and devices:

#### Example: Add a CUCM Cluster

```ini
[CUCM:production]
server=192.168.10.100
username=axl_user
password=
version=15.0
```

#### Example: Add a CUBE Device

```ini
[CUBE:router1]
host=192.168.20.2
hostname=aawoods-vg-8000v
username=admin
password=
port=22
device_type=cisco_ios
```

#### Example: Add a CUC Cluster

```ini
[CUC:main]
server=192.168.10.120
username=admin
password=
version=15.0
```

### Step 3: Set File Permissions (Recommended)

```bash
chmod 600 .env/credentials.env
```

This restricts access to your credentials file.

### Step 4: Test the Configuration

```bash
python3 setup/test_credentials_loader.py
```

Expected output:
```
Testing CredentialsLoader
================================================================================
Loaded credentials from: /path/to/.env/credentials.env

All credentials found: 3
  - CUCM:production
  - CUBE:router1
  - CUC:main

================================================================================
CUCM Credentials:
Found 1 CUCM cluster(s):
  - production
    Server: 192.168.10.100
    Version: 15.0
    Username: axl_user
...
```

## Password Handling

### Option 1: Blank Password (Recommended for Production)

Leave the password blank in the credentials.env file:

```ini
[CUCM:production]
password=
```

When a script runs and needs the password, you'll be prompted:
```
Enter password for CUCM 'production': *** (input hidden)
```

**Advantages:**
- Passwords never stored in files
- Secure even if file is compromised
- Meets security best practices

### Option 2: Stored Password (For Testing Only)

Store the password in the credentials.env file:

```ini
[CUCM:test]
password=test_password_123
```

**Disadvantages:**
- Password stored in plaintext
- Not recommended for production
- File must be carefully protected

**Important:** Per the CLAUDE.md hard rule, passwords are NEVER displayed on screen when prompted. The system uses `getpass.getpass()` to hide password input.

## File Structure

After setup, your project structure looks like:

```
uc-automation/
├── .env/                          # Local configuration (NEVER commit)
│   ├── credentials.env            # Your actual credentials
│   └── customer_env.json          # Your customer settings
│
├── .env.EXAMPLE/                  # Templates (ALWAYS commit these)
│   ├── credentials.env.EXAMPLE    # Template for credentials
│   ├── customer_env.json.EXAMPLE  # Template for customer settings
│   ├── README.md                  # Config overview
│   ├── CREDENTIALS_ENV_README.md  # Detailed reference
│   └── INTEGRATION_GUIDE.md       # How to use in scripts
│
├── setup/
│   ├── env_loader.py              # EnvironmentConfig + CredentialsLoader
│   └── test_credentials_loader.py # Test script
│
└── cube/
    ├── check_router_mem_status.py # Example script using CredentialsLoader
    └── routers.csv                # (Optional) Device list
```

## Using Credentials in Your Scripts

### CUCM Scripts

Old way (cucm-info.json):
```python
def main():
    config_path = input("Path to cucm-info.json: ")
    with open(config_path) as f:
        config = json.load(f)
```

New way (credentials.env):
```python
from setup.env_loader import CredentialsLoader

def main():
    creds_loader = CredentialsLoader()
    config = creds_loader.get_cucm_credentials('production')
    
    if not config:
        print("Cluster 'production' not found in credentials.env")
        return
```

### CUBE Scripts

Old way (routers.csv + manual prompts):
```python
def main():
    routers = read_csv_routers('routers.csv')
    username = input("SSH username: ")
    password = getpass.getpass("SSH password: ")
```

New way (credentials.env):
```python
from setup.env_loader import CredentialsLoader

def main():
    creds_loader = CredentialsLoader()
    devices = creds_loader.get_cube_credentials()
    
    for device in devices:
        # Password prompting happens automatically if blank
        connect_and_execute(device)
```

### Multi-Cluster Example

```python
from setup.env_loader import CredentialsLoader

def main():
    creds_loader = CredentialsLoader()
    
    # Get all CUCM clusters
    clusters = creds_loader.get_cucm_credentials()
    
    for cluster in clusters:
        print(f"Processing: {cluster['identifier']}")
        # cluster has: server, username, password, version, identifier
```

## Available Service Types

### CUCM (Cisco Unified Communications Manager)

Requires: `server`, `username`, `password`, `version`

```ini
[CUCM:production]
server=192.168.10.100
username=axl_user
password=
version=15.0

[CUCM:staging]
server=192.168.10.101
username=axl_user
password=
version=15.0
```

### CUC (Cisco Unity Connection)

Requires: `server`, `username`, `password`, `version`

```ini
[CUC:primary]
server=192.168.10.120
username=admin
password=
version=15.0
```

### CUBE (Cisco Unified Border Element)

Requires: `host`, `hostname`, `username`, `password`, `port`, `device_type`

```ini
[CUBE:router1]
host=192.168.20.2
hostname=aawoods-vg-8000v
username=admin
password=
port=22
device_type=cisco_ios

[CUBE:router2]
host=192.168.20.5
hostname=aw-slab42-lg
username=admin
password=
port=22
device_type=cisco_ios
```

### WEBEX

Requires: `api_token` (optional: `org_id`)

```ini
[WEBEX:main]
api_token=your_token_here
org_id=your_org_id
```

## CredentialsLoader API

```python
from setup.env_loader import CredentialsLoader

loader = CredentialsLoader()

# Get all clusters/devices of a type
all_cucm = loader.get_cucm_credentials()      # Returns list or empty list
all_cuc = loader.get_cuc_credentials()        # Returns list or empty list
all_cube = loader.get_cube_credentials()      # Returns list or empty list
all_webex = loader.get_webex_credentials()    # Returns list or empty list

# Get specific cluster/device (prompts for password if blank)
one_cucm = loader.get_cucm_credentials('production')
one_cube = loader.get_cube_credentials('router1')

# List credential identifiers
all_services = loader.list_credentials()              # All [SERVICE:name]
cucm_only = loader.list_credentials('CUCM')          # Only CUCM
cube_only = loader.list_credentials('CUBE')          # Only CUBE
cuc_only = loader.list_credentials('CUC')            # Only CUC
webex_only = loader.list_credentials('WEBEX')        # Only WEBEX

# Returns dict with all fields from credentials.env plus 'identifier' key
# Example: {'identifier': 'production', 'server': '192.168.10.100', ...}
```

## Troubleshooting

### Test fails: "No CUCM credentials found"

1. Check that credentials.env exists:
   ```bash
   ls -l .env/credentials.env
   ```

2. Check file has correct sections:
   ```bash
   grep "^\[CUCM:" .env/credentials.env
   ```

3. Verify INI format is correct:
   ```bash
   python3 -m configparser .env/credentials.env
   ```

### Test fails: "No credentials found"

Run the test with verbose output:
```bash
python3 setup/test_credentials_loader.py
```

Check the first line of output shows the loaded file path is correct.

### Password prompt not working in scripts

1. Ensure password field in credentials.env is blank:
   ```ini
   password=
   ```
   Not:
   ```ini
   password =   # (extra spaces)
   password     # (missing =)
   ```

2. Ensure you're calling the right getter method:
   ```python
   # For password prompting, use identifier parameter
   creds = loader.get_cucm_credentials('production')  # Correct
   
   # Don't do this:
   creds = loader.get_cucm_credentials()  # Returns list without prompting
   ```

### Wrong credentials loaded

1. Check section name matches identifier:
   ```python
   # If section is [CUCM:prod]
   creds = loader.get_cucm_credentials('prod')  # Correct
   
   # This will fail:
   creds = loader.get_cucm_credentials('production')  # Wrong name
   ```

2. List available sections:
   ```python
   all_services = loader.list_credentials('CUCM')
   print(all_services)  # Shows actual section names
   ```

## Git Configuration

Ensure credentials.env is never committed:

The `.gitignore` file already includes `.env`, which prevents this directory from being tracked. Verify:

```bash
git status --ignored | grep ".env"
```

Should show:
```
Ignored files:
  (use "git add -f" to include the anyway)
    .env/
```

## Documentation

For more details, see:

- **[.env.EXAMPLE/README.md](.env.EXAMPLE/README.md)** - Configuration overview
- **[.env.EXAMPLE/CREDENTIALS_ENV_README.md](.env.EXAMPLE/CREDENTIALS_ENV_README.md)** - Detailed credentials reference
- **[.env.EXAMPLE/INTEGRATION_GUIDE.md](.env.EXAMPLE/INTEGRATION_GUIDE.md)** - How to integrate into scripts
- **[.env.EXAMPLE/CUSTOMER_ENV_README.md](.env.EXAMPLE/CUSTOMER_ENV_README.md)** - Customer settings reference

## Next Steps

1. Set up your credentials.env file
2. Run the test script to verify
3. Update your scripts to use CredentialsLoader (see INTEGRATION_GUIDE.md)
4. Commit `.env.EXAMPLE/` files but never commit `.env/` directory
