# check_router_mem_status.py Setup Instructions

The `check_router_mem_status.py` script uses the shared UC automation router
selector and credentials.env for credential management. Routers are read
from `_DATA/routers.csv`.

## How It Works

1. Router list: read from `_DATA/routers.csv` via the shared router selector
2. Credentials: from `.env/credentials.env`, using the standard
   `[CUBE:default]` / `[CUBE:<hostname>]` flow shared by all CUBE scripts
3. Run with `python3 main.py` (menu entry: "Router Memory Status") or
   directly with `python3 cube/check_router_mem_status.py`

## Setup Steps

### Step 1: Create/Update routers.csv

Location: `_DATA/routers.csv`

CSV format:
```csv
router_ip,hostname
192.168.20.2,aawoods-vg-8000v
192.168.20.5,aw-slab42-lg
```

An example is provided at `_DATA/examples/routers.csv.EXAMPLE`.

### Step 2: Add Credentials to credentials.env

**Option A: Single credential set for all routers**

```ini
[CUBE:default]
username=admin
password=
```

**Option B: Per-router credentials**

Match section names to router hostnames from the CSV:

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
python3 main.py
```

or directly:

```bash
python3 cube/check_router_mem_status.py
```

You'll be prompted for:
1. **Use multiple routers?** - Yes to run against every router in
   routers.csv, No to pick a single router from the list
2. **Credentials** - if multiple routers, "Use same credentials for all
   routers?"; the loader checks `[CUBE:<hostname>]` first, then
   `[CUBE:default]`, then prompts
3. **Send summary email?** - Yes to email the results using the
   `customer_env.json` email settings

### Step 4: Scheduled / non-interactive runs

Use the `-d` / `--default` flag for cron or scheduled runs:

```bash
python3 cube/check_router_mem_status.py --default
```

In `--default` mode the script:
- Uses every router in `_DATA/routers.csv`
- Uses `[CUBE:default]` credentials without prompting (falls back to a
  password prompt only if no password is stored, since there is no other
  source of credentials in this mode)
- Skips the customer variable confirmation prompt
- Sends the summary email automatically

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

## Customer Variables

`low_memory_threshold` (default 33) is stored in `.var/check_router_mem_status.var`,
created interactively on first run from `.var/examples/check_router_mem_status.var.EXAMPLE`.

## Troubleshooting

### "No routers found in _DATA/routers.csv"

1. Check the file exists:
   ```bash
   ls -la _DATA/routers.csv
   ```
2. If missing, copy from the example and edit:
   ```bash
   cp _DATA/examples/routers.csv.EXAMPLE _DATA/routers.csv
   ```

### "CSV must contain 'router_ip' and 'hostname' columns"

CSV headers required: `router_ip`, `hostname`.

### No credentials found for a router

The credential loader checks `[CUBE:<hostname>]`, then `[CUBE:default]`,
then prompts interactively. Add an entry to `.env/credentials.env` to avoid
being prompted every run.

### Connection timeout

1. Verify router IP is correct in the CSV
2. Verify router is reachable: `ping <ip>`
3. Verify SSH is enabled on the router (default port 22)

### Authentication failed

1. Verify username and password are correct
2. Check router logs for failed attempts
3. Verify the user has SSH access

## Code Architecture

### Key Features
- Router discovery via the shared `_DATA/routers.csv` selector
- Centralized credentials via `.env/credentials.env`
- Single-router and multi-router (all routers) modes
- `--default` flag for unattended scheduled runs
- Automatic hostname-based credential matching

### Main Function Flow
1. Start logger, log "Router Memory Status - Started"
2. Load customer variables (`low_memory_threshold`)
3. Select router(s) and credentials
4. Execute the memory status command on each router
5. Display results, log "Router Memory Status - Completed"
6. Optionally send a summary email

## Questions?

See these files for more details:
- `.env.EXAMPLE/CREDENTIALS_ENV_README.md` - Credentials reference
- `.env.EXAMPLE/INTEGRATION_GUIDE.md` - Integration guide
- `CREDENTIALS_SETUP.md` - Full setup documentation
