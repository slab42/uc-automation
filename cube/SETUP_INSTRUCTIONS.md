# check_router_mem_status.py Setup Instructions

The `check_router_mem_status.py` script now uses credentials.env for credential management while reading router IPs and names from routers.csv.

## How It Works

1. Router list: Read from routers.csv (IP + hostname)
2. Credentials: From credentials.env (username + password)
3. Two credential modes: Single or per-router credentials

## Setup Steps

### Step 1: Create/Update routers.csv

The routers.csv file is located in the central **_DATA** folder.

Location: `_DATA/routers.csv`

CSV format (headers are searched by name):
```csv
router_ip,hostname
192.168.20.2,aawoods-vg-8000v
192.168.20.5,aw-slab42-lg
```

Keys searched: `router_ip`, `ip`, `address` (for IP)
Keys searched: `hostname`, `name`, `router_name` (for hostname)

Note: Edit `_DATA/routers.csv`, not the old `cube/routers.csv` location.

### Step 2: Add Credentials to credentials.env

Choose credential mode:

**Option A: Single credential set (simpler)**

```ini
[CUBE:default]
username=admin
password=
```

**Option B: Per-router credentials (more flexibility)**

Match section names to router hostnames from CSV:

```ini
[CUBE:aawoods-vg-8000v]
username=admin
password=

[CUBE:aw-slab42-lg]
username=user2
password=
```

### Step 3: Run the script

```bash
python3 cube/check_router_mem_status.py
```

You'll be prompted for:
1. **CSV file path** - Press Enter for default (routers.csv)
2. **Credential mode** - Choose 1 or 2:
   ```
   Credential Mode
   ================================================================================
   1. Single username/password for all routers
   2. Per-router credentials (matched by hostname in credentials.env)
   
   Select mode (1 or 2) [default: 1]: _
   ```

### Step 4: Provide credentials (if needed)

- **Mode 1**: Uses `[CUBE:default]` if present, otherwise prompts
- **Mode 2**: Uses matching hostname entries, prompts for missing ones

### Step 5: Review results and send email

Results are displayed, then optionally send summary email.

## Credential Mode Details

### Mode 1: Single Username/Password

Best for: All routers use same credentials

Flow:
1. Script checks for `[CUBE:default]` in credentials.env
2. If found and has username, offers to use it
3. Can accept stored credentials or enter new ones
4. Same credentials applied to all routers

Example:
```ini
[CUBE:default]
username=admin
password=
```

Run: `python3 cube/check_router_mem_status.py` → Select 1 → Choose to use stored or enter new

### Mode 2: Per-Router Credentials

Best for: Different routers have different credentials

Flow:
1. Script reads CSV routers
2. For each router, looks for matching `[CUBE:hostname]` entry
3. If found, uses stored credentials
4. If not found, prompts user
5. Each router can have different username/password

Example:
```ini
[CUBE:aawoods-vg-8000v]
username=admin
password=

[CUBE:aw-slab42-lg]
username=user2
password=
```

Run: `python3 cube/check_router_mem_status.py` → Select 2 → Credentials loaded from entries or prompted

## Password Handling

### Blank Password (Recommended)
```ini
[CUBE:default]
username=admin
password=
```
Script prompts at runtime (password never displayed on screen). Secure even if file is shared.

### Stored Password (Testing Only)
```ini
[CUBE:default]
username=admin
password=my_router_password
```
Script uses stored password without prompting. Not recommended for production.

## Credential Mode Comparison

| Aspect | Mode 1 (Single) | Mode 2 (Per-Router) |
|--------|-----------------|-------------------|
| Setup complexity | Simple | Medium |
| All routers same creds | ✓ Best choice | Works but overkill |
| Different creds per router | ✗ Not possible | ✓ Best choice |
| Recommended for | Uniform environments | Mixed environments |
| Entries needed | 1 (`[CUBE:default]`) | One per unique router |

## Troubleshooting

### "CSV file not found"

1. Check file exists in _DATA:
   ```bash
   ls -la _DATA/routers.csv
   ```

2. If file doesn't exist, copy from examples:
   ```bash
   cp _DATA/examples/router_config_template.EXAMPLE _DATA/routers.csv
   ```

3. Edit with actual router IPs and hostnames:
   ```bash
   # Edit _DATA/routers.csv and add your routers
   ```

4. Use custom path if needed:
   ```
   Enter path to CSV file [_DATA/routers.csv]: /custom/path/routers.csv
   ```

### "CSV must contain 'router_ip' and 'hostname' columns"

CSV headers are searched (case-insensitive):
- IP column: `router_ip`, `ip`, `address`
- Hostname column: `hostname`, `name`, `router_name`

Valid example:
```csv
router_ip,hostname
192.168.1.1,router-01
```

### "No credentials found" in Mode 2

When using per-router credentials:
1. Script looks for `[CUBE:hostname]` matching CSV hostnames
2. If not found, user is prompted
3. This is normal - add entries to credentials.env to avoid prompting

Solution - add to credentials.env:
```ini
[CUBE:aawoods-vg-8000v]
username=admin
password=

[CUBE:aw-slab42-lg]
username=admin
password=
```

### Connection timeout

1. Verify router IP is correct in CSV
2. Verify router is reachable: `ping <ip>`
3. Verify SSH is enabled on router
4. Verify SSH port (default 22)

### Authentication failed

1. Verify username is correct
2. Verify password is correct
3. Check router logs for failed attempts
4. Verify user has SSH access

## Code Architecture

### Key Features
- CSV-based router discovery (routers.csv)
- Centralized credentials (credentials.env)
- Single and per-router credential modes
- Automatic hostname-based matching
- Graceful fallback to prompting

### Main Function Flow
1. Prompt for CSV file path (default: `_DATA/routers.csv`)
2. Read routers from CSV (IP + hostname)
3. Ask credential mode (1=single, 2=per-router)
4. Load credentials from credentials.env
5. Execute commands on routers
6. Display results
7. Option to send summary email

## Next Steps

1. Create/update routers.csv with router IPs and names
2. Add credentials to credentials.env:
   - Option A: Single `[CUBE:default]` entry
   - Option B: Per-router entries matching hostnames
3. Run: `python3 cube/check_router_mem_status.py`
4. Select credential mode when prompted
5. Review results, send email if desired

## Questions?

See these files for more details:
- `.env.EXAMPLE/CREDENTIALS_ENV_README.md` - Credentials reference
- `.env.EXAMPLE/INTEGRATION_GUIDE.md` - Integration guide
- `CREDENTIALS_SETUP.md` - Full setup documentation
