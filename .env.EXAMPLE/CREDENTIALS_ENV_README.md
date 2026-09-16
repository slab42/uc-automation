# Credentials Configuration

The `credentials.env` file centrally manages credentials for all UC automation services (CUCM, CUC, CUBE, Webex). This replaces individual credential files and enables multi-cluster/multi-device operations.

## File Location

```
.env/credentials.env          <- Actual credentials (keep secure, don't commit)
.env.EXAMPLE/credentials.env.EXAMPLE  <- Template for new installations
```

## File Format

The file uses INI-style sections with `[SERVICE:identifier]` naming:

```ini
[CUCM:cluster_name]
server=ip_address
username=user
password=secret_or_blank
version=15.0

[CUC:cluster_name]
server=ip_address
username=user
password=secret_or_blank
version=15.0

[CUBE:device_name]
host=ip_address
hostname=router_name
username=user
password=secret_or_blank
port=22
device_type=cisco_ios

[WEBEX:cluster_name]
api_token=token
org_id=optional_org_id
```

## Service Types and Required Fields

### CUCM (Cisco Unified Communications Manager)

Required fields:
- `server` - CUCM server IP/hostname
- `username` - AXL API user
- `password` - AXL password (blank to prompt)
- `version` - CUCM version (e.g., 15.0)

Example:
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

Required fields:
- `server` - CUC server IP/hostname
- `username` - Admin user
- `password` - Admin password (blank to prompt)
- `version` - CUC version (e.g., 15.0)

Example:
```ini
[CUC:main]
server=192.168.10.120
username=admin
password=
version=15.0
```

### CUBE (Cisco Unified Border Element)

Router list comes from CSV file (routers.csv). Credentials.env contains only usernames and passwords.

Two credential modes:

**Mode 1: Single credential set (default)**
Use `[CUBE:default]` for single username/password applied to all routers:

```ini
[CUBE:default]
username=admin
password=
```

**Mode 2: Per-router credentials**
Create entries matching router hostnames from CSV:

```ini
[CUBE:aawoods-vg-8000v]
username=admin
password=

[CUBE:aw-slab42-lg]
username=user2
password=
```

Script flow:
1. Reads router IPs and hostnames from routers.csv
2. Asks user which credential mode to use
3. Single mode: Uses `[CUBE:default]` or prompts for shared credentials
4. Per-router mode: Matches each CSV hostname to credentials.env entry

If a router hostname has no matching credentials.env entry, user is prompted.

### WEBEX

Required fields:
- `api_token` - Webex admin API token
- `org_id` - (optional) Organization ID

Example:
```ini
[WEBEX:main]
api_token=your_token_here
org_id=org_id_if_needed
```

## Password Handling

### Blank Password (Recommended for Production)

Leave password blank to prompt at runtime:
```ini
[CUCM:prod]
password=
```

Scripts will prompt:
```
Enter password for CUCM 'prod': *** (hidden input)
```

### Stored Password

Store password in file (not recommended for production):
```ini
[CUCM:test]
password=my_insecure_password
```

Scripts will use stored password without prompting.

## Using Credentials in Scripts

### Python Scripts

```python
from setup.env_loader import CredentialsLoader

# Initialize loader
creds_loader = CredentialsLoader()

# Get all CUCM clusters
cucm_clusters = creds_loader.get_cucm_credentials()
for cluster in cucm_clusters:
    print(f"Cluster: {cluster['identifier']}")
    print(f"  Server: {cluster['server']}")

# Get specific CUCM cluster with password prompting
cucm = creds_loader.get_cucm_credentials('production')
# If password was blank, user is prompted here

# Get all CUBE devices
cubes = creds_loader.get_cube_credentials()

# Get specific CUBE device
router = creds_loader.get_cube_credentials('router1')

# List available credentials
all_creds = creds_loader.list_credentials()  # All services
cucm_only = creds_loader.list_credentials('CUCM')  # Only CUCM
```

### Migration from Old Credential Format

#### From cucm-info.json (CUCM)

Old format:
```json
{
  "server": "192.168.1.1",
  "username": "axl_user",
  "password": "",
  "version": "15.0"
}
```

New format in credentials.env:
```ini
[CUCM:cluster_name]
server=192.168.1.1
username=axl_user
password=
version=15.0
```

#### From routers.csv (CUBE)

Old format:
```csv
router_ip,hostname
192.168.20.2,router-01
192.168.20.5,router-02
```

New format in credentials.env:
```ini
[CUBE:router1]
host=192.168.20.2
hostname=router-01
username=admin
password=
port=22
device_type=cisco_ios

[CUBE:router2]
host=192.168.20.5
hostname=router-02
username=admin
password=
port=22
device_type=cisco_ios
```

## Security Best Practices

1. **Don't commit actual credentials** - Only commit `.env.EXAMPLE/credentials.env.EXAMPLE`
2. **Use blank passwords** - Store passwords outside the file and prompt at runtime
3. **Restrict file permissions** - `chmod 600 .env/credentials.env`
4. **Use environment variables** - Consider storing sensitive data in env vars instead
5. **Rotate credentials** - Periodically update API tokens and passwords

## Adding New Service Types

To extend for new services:

1. Add section to `credentials.env.EXAMPLE`:
   ```ini
   [NEWSERVICE:identifier]
   required_field=value
   ```

2. Add getter method to `CredentialsLoader` in `setup/env_loader.py`:
   ```python
   def get_newservice_credentials(self, identifier=None):
       # Implementation similar to get_cucm_credentials()
   ```

3. Scripts can now call:
   ```python
   creds = creds_loader.get_newservice_credentials('identifier')
   ```
