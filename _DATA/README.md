# _DATA Folder

Central repository for input files and default output directory for UC automation scripts.

## Purpose

- **Input files** - All scripts read data files from this folder
- **Output files** - All scripts write CSV/JSON output to this folder
- **Centralized** - Single location for all data (not scattered across subdirectories)
- **Organized** - Easier to find, back up, and version control

## Structure

```
_DATA/
├── README.md                           (this file)
├── routers.csv                         (CUBE router list)
├── audioCodecPreferenceLists.csv       (CUCM audio codec data)
├── clusters.csv                        (Cluster reference data)
├── examples/                           (Example templates)
│   ├── router_config_template.EXAMPLE
│   ├── mailboxs.csv.EXAMPLE
│   └── createRegions.csv.EXAMPLE
└── [output files created by scripts]
    (created automatically as scripts run)
```

## Input Files

### routers.csv
**Used by:** `cube/check_router_mem_status.py`

Format:
```csv
router_ip,hostname
192.168.20.2,aawoods-vg-8000v
192.168.20.5,aw-slab42-lg
```

### clusters.csv
**Used by:** CUCM scripts (reference)

Format:
```csv
clusterType,clusterName,server,version
cucm,cucm1,192.168.10.100,15.0
cuc,cuc1,192.168.10.120,15.0
```

### audioCodecPreferenceLists.csv
**Used by:** CUCM audio codec scripts

Format: Depends on specific script requirements

## Example Files

Templates for creating new input files:

- `examples/router_config_template.EXAMPLE` - CUBE router config template
- `examples/mailboxs.csv.EXAMPLE` - CUC mailbox data template
- `examples/createRegions.csv.EXAMPLE` - CUCM region creation template

Copy and customize as needed for your environment.

## Output Files

Scripts automatically create output files in this folder:

- `*.csv` - CSV output from bulk operations
- `*.json` - JSON configuration exports
- `*.log` - Execution logs (if configured)

Example output files created by scripts:
```
_DATA/createRegions_results.csv
_DATA/users_export.json
_DATA/bulk_operation_results.csv
```

## Using _DATA in Scripts

### Python Scripts

**Reading from _DATA:**
```python
import os
from pathlib import Path

# Get path relative to script
data_dir = Path(__file__).parent.parent / "_DATA"
csv_path = data_dir / "routers.csv"

with open(csv_path, 'r') as f:
    # read file
```

**Or with default prompt:**
```python
csv_input = input("Enter path to CSV file [_DATA/routers.csv]: ").strip()
if not csv_input:
    csv_input = "../_DATA/routers.csv"
```

**Writing to _DATA:**
```python
output_path = data_dir / f"output_{timestamp}.csv"
with open(output_path, 'w') as f:
    # write file
```

## File Organization Guidelines

1. **Raw input files** - Keep in _DATA root (routers.csv, clusters.csv)
2. **Templates/Examples** - Keep in _DATA/examples/
3. **Output files** - Automatically created in _DATA root
4. **Do NOT move** - .env files, customer_env files, .claude/, .vscode/

## Git Ignore

Add to `.gitignore` to prevent committing sensitive data:

```
# _DATA folder
_DATA/*.csv
_DATA/*.json
_DATA/*_output*
_DATA/*_results*

# Keep examples and templates
!_DATA/examples/
```

This way, only example templates are committed, not actual data files.

## Migration Guide

Existing code that expects files in subdirectories:

**Before:**
```python
csv_path = "routers.csv"  # in cube/ folder
```

**After:**
```python
csv_path = "../_DATA/routers.csv"  # from cube/check_router_mem_status.py
# or
from pathlib import Path
csv_path = Path(__file__).parent.parent / "_DATA" / "routers.csv"
```

## Script Updates

List of scripts updated to use _DATA:

- ✓ `cube/check_router_mem_status.py` - Default path now _DATA/routers.csv
- [ Other scripts to be updated as needed

## Default Paths by Script

| Script | Input File | Output Folder |
|--------|-----------|---------------|
| `cube/check_router_mem_status.py` | `_DATA/routers.csv` | `_DATA/` |
| `cucm/[scripts]` | `_DATA/*.csv` | `_DATA/` |
| `cuc/[scripts]` | `_DATA/*.csv` | `_DATA/` |
| `webex/[scripts]` | `_DATA/*.csv` | `_DATA/` |

## Backup Considerations

Since _DATA contains important configuration data:

1. Back up _DATA folder regularly
2. Keep examples folder for documentation
3. Consider version control for non-sensitive data
4. Export critical configurations periodically

## Questions?

See related documentation:
- `CREDENTIALS_SETUP.md` - Credentials and environment configuration
- `.env.EXAMPLE/README.md` - Configuration file structure
- Individual script README files in subdirectories
