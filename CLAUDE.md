# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

uc-automation is a collection of Python scripts for Unified Communications automation across on-premise (CUCM) and cloud (Webex) platforms. CUCM scripts use Cisco's AXL SOAP API via zeep; Webex scripts use REST APIs.

## Directory Structure

- **cucm/** - Cisco Unified Communications Manager automation scripts
  - Individual operation scripts (add/remove/move patterns, update phone loads, etc.)
  - `general.py` - Shared utilities for config, logging, HTTP setup
  - `ucmAPI.py` - AXL SOAP client wrapper class around zeep
  - `schema/<version>/` - WSDL files required for AXL (one per CUCM version)
  - `logs/` - Timestamped log files from script runs
  - `*.csv.EXAMPLE` or `*.csv` - Configuration files for bulk operations
  - `cucm-info.json.EXAMPLE` - Template for server credentials

- **webex/** - Webex/Calling automation scripts
  - Individual operation scripts for locations, users, call queues, etc.
  - Typically use `general.py` from cucm/

  - `GET /telephony/config/locations` (Calling admin API, `spark-admin:telephony_config_read`) and `GET /v1/locations` (core/base Locations API, `spark-admin:locations_read`) are **different API families with different scopes** — this app's integration has the former, not the latter. Don't confuse them when debugging location-related 403s.

- **cuc/** - Cisco Unity automation scripts
 - Schema artifacts
 - Use application.wadl file for schema first

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

## Running CUCM Scripts

All CUCM scripts follow the same pattern:

1. Copy template: `cp cucm-info.json.EXAMPLE cucm-info.json`
2. Fill in CUCM server details, AXL username, password, and version
3. Run script: `python3 script_name.py`
4. Interactive prompts:
   - Path to config file (defaults to `cucm-info.json`)
   - Single item or CSV bulk mode
   - For CSV mode, path to CSV file (defaults to a predictable name like `mv_dnPartitions.csv`)
5. Logs written to `logs/<timestamp>-<script_name>.log`

Example:
```bash
python3 move_DN_partition.py
# Prompts for config file
# Prompts for CSV mode (y/n)
# Processes moves from mv_dnPartitions.csv
# Logs to logs/2025-XX-XX_HH-MM-SS-move_DN_partition.log
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

Scripts check version from config and load: `cucm/schema/{version}/AXLAPI.wsdl`

If running against a new CUCM version:
1. Download AXLAPI.wsdl from CUCM server or Cisco documentation
2. Place in `cucm/schema/<new_version>/`
3. Update `cucm-info.json` version field

## Configuration Files

- `cucm-info.json` - credentials and CUCM details (JSON):
  ```json
  {
    "server": "192.168.1.1",
    "username": "axl_user",
    "password": "password_or_blank_to_prompt",
    "version": "15.0"
  }
  ```
  If password is blank, script prompts at runtime (recommended for security).

- `.csv` files for bulk operations - field order matters; headers are skipped by search for known headers. Scripts ignore extra fields to allow flexible templates.

## Architecture Patterns

**Interactive Flow:**
- Prompt for config file path
- Prompt for single vs. CSV mode
- Read target data (single input or CSV rows)
- Call AXL API via ucmAPI.AXL class
- Log each operation result
- Final summary

**Error Handling:**
- AXL API errors caught as zeep.exceptions.Fault; logged with error message
- CSV parsing is lenient: searches for column headers and ignores extra fields
- Network retries handled by httpSetup() session

**Logging:**
- All scripts use dual-output logging (stdout + file)
- File logs in `logs/` with timestamp and script name
- Log level: DEBUG (all operations logged)

## Common Development Tasks

**Adding a new CUCM script:**
1. Import general.py and ucmAPI.AXL
2. Follow the pattern: config setup, logger setup, prompt for mode, process data, call AXL, log results
3. Document CSV field order in docstring
4. Test with CUCM sandbox if available

**Extending ucmAPI.py:**
1. Add method to AXL class
2. Name as `verb_noun()` (e.g., `add_line()`, `remove_device()`)
3. Return standard dict: `{'success': bool, 'response': str, 'error': str}`
4. Catch zeep.exceptions.Fault and populate error field

**Debugging AXL calls:**
- Check logs/ directory for detailed operation trace
- CUCM server logs available on CUCM admin GUI
- Zeep's HistoryPlugin attached to AXL client (rarely needed but available for inspection)
