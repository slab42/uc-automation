# uc-automation
Collection of On-Prem and Cloud Scripts for UC Automation

## CUCM Scripts

All scripts below are interactive AXL scripts for Cisco Unified Communications Manager (CUCM). Each one:

- Prompts for a CUCM JSON file (default: `cucm-info.json`) containing `server`, `username`, `password`, and `version`. If `password` is blank, you will be prompted to enter it.
- Prompts `Use CSV?: (y/n)` to choose between editing a single item or bulk processing a CSV file.
- Logs to both stdout and a timestamped file under `logs/`.
- Requires the matching AXL WSDL schema under `schema/<version>/AXLAPI.wsdl`.

Copy `cucm-info.json.EXAMPLE` to `cucm-info.json` and fill in your server details before running.

### add_advertisted_pattern.py
Adds one or more Advertised Patterns (Hosted DN/PSTN patterns).

CSV (default: `advertisedPatterns.csv`), field order:
```
description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend
```
`patternType`: `+E.164 Number`, `Enterprise Number`
`hostedRoutePSTNRule`: `No PSTN`, `Use pattern`, `Specify`

### remove_advertisted_pattern.py
Removes one or more Advertised Patterns. If removal fails and the pattern does not already start with `+`, the script automatically retries with a `+` prefix.

CSV (default: `rm_advertisedPatterns.csv`), field order:
```
pattern
```

### remove_DN_EnterpriseAlternateNumber.py
Verifies a DN exists in the given partition, then clears its Enterprise Alternate Number settings (whether or not one is currently set).

CSV (default: `rm_dnEnterpriseAltNumbers.csv`), field order:
```
dn, routePartition
```

### move_DN_partition.py
Verifies a DN exists in its current partition, then moves it to a new Route Partition.

CSV (default: `mv_dnPartitions.csv`), field order:
```
pattern, routePartition, newRoutePartition
```

## Support Modules

### general.py
Shared helpers used by all scripts: `serverSetup` (reads the CUCM JSON file), `loggerSetup` (stdout + rotating file logging), `httpSetup` (HTTP session with retries), and `findFiles`.

### ucmAPI.py
`AXL` client wrapper around the Cisco AXL SOAP API (zeep) used by all scripts to get/add/update/remove CUCM objects (Lines, Phones, Advertised Patterns, Translation Patterns, Users, Device Pools, Media Resource Lists, etc).
