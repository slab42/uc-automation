# UC Automation Configuration

This directory contains templates and documentation for configuring UC automation.

## Files in This Directory

### credentials.env.EXAMPLE
Template for credentials configuration. Contains placeholders for:
- CUCM clusters (username, password, server, version)
- CUC clusters (username, password, server, version)  
- CUBE devices/routers (username, password, host, port, device_type)
- Webex credentials (API token, org ID)

Copy to `.env/credentials.env` and fill in your actual values.

### customer_env.json.EXAMPLE
Template for customer-specific settings (email server, alert thresholds). Used by EnvironmentConfig class.

### clusters.csv.EXAMPLE
Reference CSV showing how to list clusters. Format: clusterType, clusterName, server, version.

### CREDENTIALS_ENV_README.md
Complete reference for the credentials.env file:
- File format and structure
- Required fields for each service type
- Password handling (blank to prompt, or stored)
- Usage examples in Python scripts
- Migration from old formats
- Security best practices

### INTEGRATION_GUIDE.md
Step-by-step guide for integrating CredentialsLoader into scripts:
- Quick start setup
- Before/after code examples for CUCM, CUBE, and Webex scripts
- Multi-cluster handling
- Migration path from manual config loading
- Advanced usage (env vars, custom paths, validation)
- Troubleshooting guide

### CUSTOMER_ENV_README.md
Documentation for customer_env.json configuration.

## Quick Start

1. Copy templates to .env/:
   ```bash
   cp credentials.env.EXAMPLE ../.env/credentials.env
   cp customer_env.json.EXAMPLE ../.env/customer_env.json
   ```

2. Edit `.env/credentials.env` and add your clusters:
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

3. Test the configuration:
   ```bash
   cd ../.. && python3 setup/test_credentials_loader.py
   ```

## How It Works

The setup directory contains two loader classes:

### EnvironmentConfig (env_loader.py)
Loads `customer_env.json` for:
- Email server configuration
- Alert thresholds
- Other customer-specific settings

Usage:
```python
from setup.env_loader import EnvironmentConfig

env_config = EnvironmentConfig()
email_cfg = env_config.get_email_config()
threshold = env_config.get_memory_threshold()
```

### CredentialsLoader (env_loader.py)
Loads `credentials.env` for all cluster/device credentials.

Services supported:
- CUCM - Cisco Unified Communications Manager clusters
- CUC - Cisco Unity Connection clusters
- CUBE - Cisco Unified Border Element devices
- WEBEX - Webex calling and admin APIs

Usage:
```python
from setup.env_loader import CredentialsLoader

creds_loader = CredentialsLoader()

# Get all CUCM clusters
clusters = creds_loader.get_cucm_credentials()

# Get specific cluster (with password prompting if blank)
cucm = creds_loader.get_cucm_credentials('production')

# Get all CUBE devices
devices = creds_loader.get_cube_credentials()

# List available credentials
all_services = creds_loader.list_credentials()
cucm_only = creds_loader.list_credentials('CUCM')
```

## Logging Configuration

Controls the verbosity of script console output. Configuration is checked in this order:
1. **CONSOLE_LOG_LEVEL environment variable** (if set)
2. **logging.console_log_level in customer_env.json** (if configured)
3. **Default: INFO** (clean, minimal output)

Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### Configuration Methods

**Option 1: Environment Variable (one-time)**
```bash
# Verbose output with debug messages
export CONSOLE_LOG_LEVEL=DEBUG
python3 cucm/list_softkey_templates.py

# Quiet output (warnings and errors only)
CONSOLE_LOG_LEVEL=WARNING python3 script.py
```

**Option 2: customer_env.json (persistent)**
```json
{
  "logging": {
    "console_log_level": "DEBUG"
  }
}
```

Now all scripts use DEBUG level on console without setting env vars:
```bash
python3 cucm/list_softkey_templates.py  # Uses DEBUG from config
python3 cucm/move_DN_partition.py       # Uses DEBUG from config
```

**Option 3: Override config with env var**
```bash
# customer_env.json has DEBUG, but this script uses WARNING
CONSOLE_LOG_LEVEL=WARNING python3 cucm/list_softkey_templates.py
```

**Behavior:**
- Console (screen): Respects configured log level
- Log file: Always captures DEBUG level for troubleshooting
- Environment variable overrides customer_env.json setting

## Password Security

### Blank passwords (recommended)
```ini
[CUCM:production]
password=
```
Scripts will prompt at runtime:
```
Enter password for CUCM 'production': *** (hidden)
```

### Stored passwords (not recommended for production)
```ini
[CUCM:test]
password=my_password
```
Scripts use stored password without prompting.

**Important:** Per CLAUDE.md hard rule, passwords are never displayed on screen when prompted.

## File Structure

```
uc-automation/
├── .env/                          # Local configuration (don't commit)
│   ├── credentials.env            # Your actual credentials
│   └── customer_env.json          # Your customer settings
├── .env.EXAMPLE/                  # Template directory (commit these)
│   ├── credentials.env.EXAMPLE    # Credential template
│   ├── customer_env.json.EXAMPLE  # Customer settings template
│   ├── clusters.csv.EXAMPLE       # Reference CSV
│   ├── README.md                  # This file
│   ├── CREDENTIALS_ENV_README.md  # Detailed credentials reference
│   ├── INTEGRATION_GUIDE.md       # How to use in scripts
│   └── CUSTOMER_ENV_README.md     # Customer config docs
└── setup/
    ├── env_loader.py              # EnvironmentConfig + CredentialsLoader
    └── test_credentials_loader.py # Test script
```

## Migration from Old Format

### CUCM

Old: Individual `cucm-info.json` per script
```json
{
  "server": "192.168.1.1",
  "username": "axl_user",
  "password": "",
  "version": "15.0"
}
```

New: Single entry in `credentials.env`
```ini
[CUCM:cluster_name]
server=192.168.1.1
username=axl_user
password=
version=15.0
```

### CUBE

Old: `routers.csv` + interactive SSH username/password prompt
```csv
router_ip,hostname
192.168.20.2,router-01
```

New: Entries in `credentials.env`
```ini
[CUBE:router1]
host=192.168.20.2
hostname=router-01
username=admin
password=
port=22
device_type=cisco_ios
```

## Adding New Service Types

To add support for a new service:

1. Add section to `credentials.env.EXAMPLE`:
   ```ini
   [NEWSERVICE:identifier]
   field1=value1
   field2=value2
   ```

2. Add getter method to CredentialsLoader:
   ```python
   def get_newservice_credentials(self, identifier=None):
       # Similar pattern to get_cucm_credentials()
   ```

3. Update this README with new section

## Support

For issues with:
- Credentials format: See CREDENTIALS_ENV_README.md
- Script integration: See INTEGRATION_GUIDE.md
- Customer settings: See CUSTOMER_ENV_README.md

Test with:
```bash
python3 setup/test_credentials_loader.py
```

## Git Ignore

Ensure `.env/credentials.env` is never committed:

```bash
# .gitignore
.env/credentials.env
.env/customer_env.json
```

Only commit `.env.EXAMPLE/` files.
