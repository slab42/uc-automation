# UC Automation Project Structure

## Overview

This document describes the organization of the UC Automation project and where different types of files are stored.

## Directory Structure

```
uc-automation/
├── _DATA/                          ← Central data folder (INPUT and OUTPUT)
│   ├── README.md
│   ├── routers.csv                 (CUBE routers list)
│   ├── clusters.csv                (cluster reference data)
│   ├── audioCodecPreferenceLists.csv
│   └── examples/                   (example/template files)
│       ├── router_config_template.EXAMPLE
│       ├── mailboxs.csv.EXAMPLE
│       └── createRegions.csv.EXAMPLE
│
├── .env/                           ← Local configuration (NOT committed)
│   ├── credentials.env             (usernames/passwords)
│   └── customer_env.json           (email, alerts, thresholds)
│
├── .env.EXAMPLE/                   ← Configuration templates (committed)
│   ├── README.md
│   ├── credentials.env.EXAMPLE
│   ├── customer_env.json.EXAMPLE
│   ├── CREDENTIALS_ENV_README.md
│   ├── INTEGRATION_GUIDE.md
│   ├── IMPLEMENTATION_CHECKLIST.md
│   └── CUSTOMER_ENV_README.md
│
├── setup/                          ← Shared utilities
│   ├── __init__.py
│   ├── env_loader.py               (EnvironmentConfig, CredentialsLoader)
│   ├── logger.py                   (logging setup)
│   └── test_credentials_loader.py  (test script)
│
├── cube/                           ← Cisco Unified Border Element scripts
│   ├── check_router_mem_status.py  (router memory check)
│   ├── compare_router_config.py    (config comparison)
│   ├── SETUP_INSTRUCTIONS.md
│   └── logs/                       (script output logs)
│
├── cucm/                           ← CUCM automation scripts
│   ├── add_advertisted_pattern.py
│   ├── general.py
│   ├── ucmAPI.py
│   ├── schema/
│   │   └── 15.0/                   (WSDL files per version)
│   │       └── AXLAPI.wsdl
│   └── logs/                       (script output logs)
│
├── cuc/                            ← CUC automation scripts
│   └── [CUC-specific scripts]
│
├── webex/                          ← Webex automation scripts
│   └── [Webex-specific scripts]
│
├── .claude/                        ← Claude Code configuration
│   ├── settings.json               (shared settings)
│   └── settings.local.json         (local overrides)
│
├── .vscode/                        ← VS Code configuration
│   └── settings.json
│
├── .gitignore                      ← Git ignore rules
├── CLAUDE.md                       ← Claude Code guidelines
├── CREDENTIALS_SETUP.md            ← How to set up credentials
├── PROJECT_STRUCTURE.md            ← This file
└── README.md                       ← Project overview
```

## File Type Organization

### Data Files (_DATA folder)

**Input Files** (read by scripts)
- `routers.csv` - Router IP addresses and hostnames
- `clusters.csv` - Cluster reference data
- `audioCodecPreferenceLists.csv` - Audio codec configuration
- Any `*.csv` files used by automation scripts

**Example/Template Files** (_DATA/examples/)
- `*.EXAMPLE` files - Templates for creating new input files
- Copy and customize for your environment
- Keep in examples/ folder, not root

**Output Files** (created by scripts)
- `*.csv` - Bulk operation results
- `*.json` - Configuration exports
- Created automatically in _DATA/ folder

### Configuration Files (.env folder)

**LOCAL Configuration** (.env/ - NOT COMMITTED)
- `.env/credentials.env` - Usernames and passwords for all services
- `.env/customer_env.json` - Customer-specific settings (email, thresholds)

Keep `.env/` directory in `.gitignore` - contains secrets.

**Configuration Templates** (.env.EXAMPLE/ - COMMITTED)
- `.env.EXAMPLE/credentials.env.EXAMPLE` - Template for credentials
- `.env.EXAMPLE/customer_env.json.EXAMPLE` - Template for customer settings
- Other reference and documentation files

### Scripts (cube/, cucm/, cuc/, webex/)

Each service directory contains:
- Individual operation scripts (Python files)
- `general.py` - Shared utilities for that service
- `SETUP_INSTRUCTIONS.md` or `README.md` - Service-specific documentation
- `logs/` - Output logs from script runs (usually .gitignore'd)
- `schema/` or similar - Configuration/schema files (CUCM WSDL, etc.)

### Shared Code (setup/)

- `env_loader.py` - EnvironmentConfig and CredentialsLoader classes
- `logger.py` - Logging configuration
- `test_credentials_loader.py` - Test script for credentials
- `__init__.py` - Makes setup a Python package

## File Location Rules

### Use _DATA for:
- Input CSV files (routers.csv, clusters.csv, etc.)
- Output CSV/JSON files created by scripts
- Example/template files (in examples/ subfolder)
- Any data files scripts read or write

### Use .env for:
- `credentials.env` - All usernames and passwords
- `customer_env.json` - Customer-specific configuration
- Never committed to git

### Use .env.EXAMPLE for:
- `credentials.env.EXAMPLE` - Template for credentials
- `customer_env.json.EXAMPLE` - Template for customer config
- Reference documentation (CREDENTIALS_ENV_README.md, etc.)
- Always committed to git (safe, no secrets)

### Use subdirectories (cube/, cucm/, cuc/, webex/) for:
- Service-specific Python scripts
- Service-specific configuration (CUCM WSDL, etc.)
- Service-specific logs (logs/ subfolder)
- Service-specific documentation

### Never move:
- `.env/` directory files (keep in original location)
- `customer_env.json` (keep in original location)
- `.claude/` files (Claude Code configuration)
- `.vscode/` files (VS Code configuration)
- Python script files (keep in service subdirectories)

## Git Ignore Strategy

Files that should NOT be committed:

```gitignore
# Secrets
.env/
.env/*
!.env.EXAMPLE/

# Data files (use _DATA/ examples instead)
_DATA/*.csv
_DATA/*.json
!_DATA/examples/

# Logs
*/logs/
*/logs/*

# IDE and tools
.DS_Store
__pycache__/
*.pyc
*.egg-info/
.venv/
```

## Backward Compatibility Notes

### Old file locations (before _DATA):
- `cube/routers.csv` → moved to `_DATA/routers.csv`
- `cucm/audioCodecPreferenceLists.csv` → moved to `_DATA/audioCodecPreferenceLists.csv`
- `cucm/clusters.csv` → moved to `_DATA/clusters.csv`

### Scripts updated:
- `cube/check_router_mem_status.py` - Default path now `_DATA/routers.csv`

### Migration:
If you have older scripts reading from old locations, update them to use:
```python
# From any script subdirectory:
from pathlib import Path
data_dir = Path(__file__).parent.parent / "_DATA"
csv_path = data_dir / "routers.csv"
```

## Common Tasks

### Add a new input file
1. Place file in `_DATA/` folder
2. Update script to read from `_DATA/filename`
3. Document in `_DATA/README.md`

### Create example template
1. Copy actual file to `_DATA/examples/example_name.EXAMPLE`
2. Replace sensitive data with placeholders
3. Add instructions to file header if complex

### Set up credentials
1. Copy `.env.EXAMPLE/credentials.env.EXAMPLE` to `.env/credentials.env`
2. Fill in usernames and passwords
3. Never commit `.env/credentials.env` to git

### Add output files
1. Scripts create output automatically in `_DATA/`
2. Output file pattern: `_DATA/operation_timestamp_results.csv`
3. All outputs centralized in `_DATA/` folder

## Example: Adding a New Script

If creating a new script that reads CSV input:

1. **Input file location**: `_DATA/my_input.csv`
2. **Script location**: `service/my_new_script.py`
3. **Default path in script**:
   ```python
   csv_input = input("Enter path to CSV file [_DATA/my_input.csv]: ").strip()
   if not csv_input:
       csv_input = "../_DATA/my_input.csv"
   ```
4. **Output location**: `_DATA/my_output_<timestamp>.csv`
5. **Documentation**: Add details to `_DATA/README.md`

## Size and Scope

- `_DATA/` folder: Data files only (CSVs, JSONs)
- `.env/` folder: Configuration only (credentials, settings)
- Service folders: Scripts and service-specific config
- `setup/` folder: Shared code and utilities

## Maintenance

### Regular tasks:
1. Back up `_DATA/` folder (contains important configuration)
2. Keep `.env/` folder secure (contains passwords)
3. Don't commit `.env/` files to git
4. Update `_DATA/README.md` if adding new data files

### Cleanup:
- Remove old output files from `_DATA/` after processing
- Archive completed operations
- Keep `_DATA/examples/` for reference

## References

- `_DATA/README.md` - Detailed data folder documentation
- `CREDENTIALS_SETUP.md` - How to set up credentials
- `.env.EXAMPLE/README.md` - Configuration overview
- Service-specific README files in subdirectories
