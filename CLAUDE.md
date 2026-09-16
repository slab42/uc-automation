# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

uc-automation is a collection of Python scripts for Unified Communications automation across on-premise (CUCM) and cloud (Webex) platforms. CUCM scripts use Cisco's AXL SOAP API via zeep; Webex scripts use REST APIs.

## Hard Rules
- ** Password visibility ** Anytime a script prompts for a password, it should never be displayed on screen.

## Directory Structure

- **cucm/** - Cisco Unified Communications Manager automation scripts
  - Individual operation scripts (add/remove/move patterns, update phone loads, etc.)
  - `general.py` - Shared utilities for HTTP setup (legacy, use multi_object_loader for new scripts)
  - `ucmAPI.py` - AXL SOAP client wrapper class around zeep
  - `schema/<version>/` - WSDL files required for AXL (one per CUCM version)

- **webex/** - Webex/Calling automation scripts
  - Individual operation scripts for locations, users, call queues, etc.
  - Typically use `general.py` from cucm/

  - `GET /telephony/config/locations` (Calling admin API, `spark-admin:telephony_config_read`) and `GET /v1/locations` (core/base Locations API, `spark-admin:locations_read`) are **different API families with different scopes** — this app's integration has the former, not the latter. Don't confuse them when debugging location-related 403s.

- **cuc/** - Cisco Unity automation scripts
 - Schema artifacts
 - Use application.wadl file for schema first

- **setup/** - Shared utilities and loaders
  - `multi_object_loader.py` - loads clusters/routers from CSV and manages credential prompting
  - `env_loader.py` - loads configuration and credentials from .env files
  - `logger.py` - centralized logging setup

- **_DATA/** - Configuration data
  - `clusters.csv` - cluster definitions for CUCM and CUC scripts
  - `routers.csv` - router definitions for CUBE scripts

- **.env/** - Environment configuration (not checked in)
  - `credentials.env` - credentials for all clusters and routers
  - `customer_env.json` - customer-specific configuration

## Dependencies

Install via pip:
```bash
pip install zeep requests lxml urllib3
```

Key dependencies:
- `zeep` - SOAP/WSDL client for Cisco AXL API
- `requests` - HTTP library with retry logic
- `lxml` - XML parsing
- `urllib3` - HTTP with connection pooling

Python 3.6+ required (f-strings used throughout).

## Cluster and Router Configuration

All scripts use CSV files for cluster/router definitions:
- **clusters.csv** - used by CUCM and CUC scripts (columns: cluster_name, server, version)
- **routers.csv** - used by CUBE scripts (columns: router_ip, hostname)

Files located at: `_DATA/clusters.csv` and `_DATA/routers.csv`

Example clusters.csv:
```csv
cluster_name,server,version
CUCM1,192.168.1.100,15.0
CUCM2,192.168.1.101,14.0
```

Example routers.csv:
```csv
router_ip,hostname
10.0.0.1,cube-sfo
10.0.0.2,cube-nyc
```

## Credentials Configuration

Credentials stored in `.env/credentials.env` (INI format):

```ini
[CUCM:default]
username = axl_user
password = 

[CUCM:CUCM1]
username = cucm1_user
password = 

[CUC:default]
username = cuc_admin
password = 

[CUBE:cube-sfo]
username = cube_user
password = 
```

Password can be blank to prompt at runtime (recommended for security). Credentials hierarchy:
1. Try object-specific credentials (e.g., CUCM:CUCM1, CUBE:cube-sfo)
2. Fall back to default credentials (e.g., CUCM:default, CUC:default)
3. Prompt user if neither found

For multi-object operations, script asks: "Use same credentials for all objects?" 
- Yes: loads default or single credential set
- No: prompts per-object

## Running CUCM/CUC/CUBE Scripts

All scripts follow the same pattern:

1. Run script: `python3 script_name.py`
2. Interactive prompts:
   - Select cluster (CUCM/CUC) or router (CUBE) from CSV
   - Load or prompt for credentials
   - Single item or CSV mode for operations
   - For CSV mode, path to operation CSV file
3. Logs written to `_logs/<timestamp>-<script_name>.log`

Example:
```bash
python3 cucm/move_DN_partition.py
# Prompts to select CUCM cluster from clusters.csv
# Prompts for credentials (checks CUCM:default first)
# Prompts for single or CSV mode
# Processes DNs from mv_dnPartitions.csv
# Logs to _logs/2025-XX-XX_HH-MM-SS-move_DN_partition.log
```

## CUCM Script Conventions

Each script docstring specifies its CSV format (field order matters):

- `add_advertisted_pattern.py` - adds Advertised Patterns (Hosted DN/PSTN routes)
- `remove_advertisted_pattern.py` - removes patterns; auto-retries with `+` prefix if needed
- `remove_DN_EnterpriseAlternateNumber.py` - clears alternate number settings on a DN
- `move_DN_partition.py` - moves DN to a different Route Partition
- `update_LoadServer.py` - updates phone load parameters
- `update_PhoneLoad.py` - updates phone firmware load

## Core Modules

### general.py

Provides shared utilities imported by all scripts:

- `serverSetup(configPath, logPath)` - reads JSON config file, returns server dict with keys: `server`, `username`, `password`, `version`
- `loggerSetup(logPath)` - creates dual-output logger (stdout + rotating file)
- `httpSetup()` - returns requests.Session with retry logic (for non-SOAP HTTP calls in webex scripts)
- `findFiles(searchPath, searchPattern)` - glob wrapper, returns sorted list

### ucmAPI.py

`AXL` class wraps zeep SOAP client:

- `__init__(username, password, wsdl, cucm, cucm_version)` - connects to CUCM, builds zeep client from WSDL
- Methods for each operation: `add_advertised_patterns()`, `remove_advertised_patterns()`, `add_line()`, `update_device()`, etc.
- All methods return dict: `{'success': bool, 'response': str, 'error': str}`
- SSL verification disabled (ignores urllib3 warnings)

## WSDL Schema Files

CUCM scripts require matching WSDL for the target UCM version. Store in `cucm/schema/<version>/AXLAPI.wsdl`.

Scripts load WSDL based on cluster version from clusters.csv: `cucm/schema/{version}/AXLAPI.wsdl`

If running against a new CUCM version:
1. Download AXLAPI.wsdl from CUCM server or Cisco documentation
2. Place in `cucm/schema/<new_version>/`
3. Update `_DATA/clusters.csv` with the new version

## CSV Operation Files

Operation CSV files contain the data to process (e.g., DNs to move, patterns to add). Field order matters; headers are skipped. Scripts ignore extra fields to allow flexible templates.

Examples:
- `mv_dnPartitions.csv` - DNs to move (columns: dn, partition)
- `advertisedPatterns.csv` - patterns to add (columns: description, pattern, patternType, etc.)

## Script Loading and Credential Flow

**Single-Object Scripts (most CUCM/CUC/CUBE scripts):**
1. Import from `multi_object_loader`: `get_object_for_single_operation()`, `load_credentials()`
2. Load cluster/router: select from CSV or provide manually
3. Load credentials: check stored (object-specific, then default), prompt if missing
4. Initialize AXL/API client
5. Prompt for single item or CSV mode
6. Execute operations, log results

**Multi-Object Scripts (future bulk scripts):**
1. Import from `multi_object_loader`: `get_objects_for_multi_operation()`, `load_credentials_for_multi_objects()`
2. Load all clusters/routers from CSV
3. Ask: "Use same credentials for all objects?"
4. Load credentials (once for all, or per-object)
5. Execute operations on each object, log results

**Error Handling:**
- AXL API errors caught as zeep.exceptions.Fault; logged with error message
- CSV parsing is lenient: searches for column headers and ignores extra fields
- Network retries handled by httpSetup() session

**Logging:**
- All scripts use dual-output logging (stdout + file)
- File logs in `_logs/` with timestamp and script name
- Log level: DEBUG (all operations logged)

## Common Development Tasks

**Adding a new CUCM/CUC/CUBE script:**
1. Import from `multi_object_loader`: `get_object_for_single_operation()`, `load_credentials()`
2. Import from `setup.logger`: `setup_logger()`
3. Load cluster/router and credentials (see Script Loading section above)
4. Initialize AXL (CUCM/CUC) or API client (CUBE)
5. Prompt for single vs. CSV mode
6. Process data, call API, log results
7. Document operation CSV format in docstring

**Extending ucmAPI.py:**
1. Add method to AXL class
2. Name as `verb_noun()` (e.g., `add_line()`, `remove_device()`)
3. Return standard dict: `{'success': bool, 'response': str, 'error': str}`
4. Catch zeep.exceptions.Fault and populate error field

**Debugging API calls:**
- Check `_logs/` directory for detailed operation trace
- CUCM/CUC server logs available on admin GUI
- Zeep's HistoryPlugin attached to AXL client (rarely needed)
