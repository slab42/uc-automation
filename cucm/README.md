# uc-automation
Collection of On-Prem and Cloud Scripts for UC Automation

## CUCM Scripts

All scripts below are interactive AXL scripts for Cisco Unified Communications Manager (CUCM), best run through the repo's `python3 main.py` launcher. Each one:

- Selects a cluster from `_DATA/clusters.csv` (rows with `cluster_type=cucm`), or lets you enter server details manually. Supports optional multi-cluster runs.
- Loads credentials from `.env/credentials.env` (`[CUCM:default]` or `[CUCM:<cluster_name>]`). If `password` is blank, you are prompted to enter it securely (never echoed to screen).
- Prompts `Use CSV?: (y/n)` to choose between a single item or bulk processing a CSV file.
- Input CSVs default to the `_DATA` folder, with examples provided in `_DATA/examples/`.
- Logs to both stdout and a timestamped file at repo-root `_logs/<timestamp>-<script>.log`.
- Requires the matching AXL WSDL schema under `schema/<version>/AXLAPI.wsdl`.

Run scripts via `python3 main.py` from the repo root, or invoke a script directly with `python3 cucm/<script>.py`.

### add_advertisted_pattern.py
Adds one or more Advertised Patterns (Hosted DN/PSTN patterns).

CSV (default: `_DATA/advertisedPatterns.csv`), field order:
```
description, pattern, patternType, hostedRoutePSTNRule, pstnFailStrip, pstnFailPrepend
```
`patternType`: `+E.164 Number`, `Enterprise Number`
`hostedRoutePSTNRule`: `No PSTN`, `Use pattern`, `Specify`

### remove_advertisted_pattern.py
Removes one or more Advertised Patterns. If removal fails and the pattern does not already start with `+`, the script automatically retries with a `+` prefix.

CSV (default: `_DATA/rm_advertisedPatterns.csv`), field order:
```
pattern
```

### remove_DN_EnterpriseAlternateNumber.py
Verifies a DN exists in the given partition, then clears its Enterprise Alternate Number settings (whether or not one is currently set).

CSV (default: `_DATA/rm_dnEnterpriseAltNumbers.csv`), field order:
```
dn, routePartition
```

### move_DN_partition.py
Verifies a DN exists in its current partition, then moves it to a new Route Partition.

CSV (default: `_DATA/mv_dnPartitions.csv`), field order:
```
pattern, routePartition, newRoutePartition
```

## Support Modules

### general.py
Legacy shared helpers: `serverSetup` (reads a JSON config file), `loggerSetup` (stdout + rotating file logging), `httpSetup` (HTTP session with retries), and `findFiles`. New scripts use `setup/multi_object_loader.py` instead.

### ucmAPI.py
`AXL` client wrapper around the Cisco AXL SOAP API (zeep) used by all scripts to get/add/update/remove CUCM objects (Lines, Phones, Advertised Patterns, Translation Patterns, Users, Device Pools, Media Resource Lists, etc).
