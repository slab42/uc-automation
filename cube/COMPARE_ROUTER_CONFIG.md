# Router Configuration Template Comparator

Compares Cisco router running configurations to a voice configuration template and generates HTML reports highlighting variances.

## Features

- Compare router configs to a template focused on voice sections only
- SSH connection with netmiko for multi-platform support
- Section-based comparison (ignores sections not in template)
- HTML reports with color-coded variances:
  - **Red**: Lines in template but missing from router config
  - **Blue**: Lines in router config but not in template
  - **Green**: Compliant sections
- Batch processing via CSV or single router mode
- Detailed logging to `logs/` directory

## Prerequisites

Install required Python packages:
```bash
pip install netmiko
```

Ensure SSH access to routers with appropriate credentials.

## Usage

### Setup Template

1. Copy the example template:
   ```bash
   cp router_config_template.EXAMPLE router_config_template.txt
   ```

2. Edit the template to include only the voice configuration sections you want to validate:
   - voice classes, codec preferences
   - voice-port definitions
   - dial-peer configurations
   - call-manager-fallback settings
   - telephony-service settings
   - SIP, H.323, MGCP configurations
   - Any other voice-related commands

   **Important**: Only sections present in the template will be checked. Extra sections in router configs are flagged but not required.

### Setup Router List (CSV mode)

1. Copy the example CSV:
   ```bash
   cp routers.csv.EXAMPLE routers.csv
   ```

2. Edit `routers.csv` to include your routers:
   ```csv
   router_ip,hostname
   192.168.1.10,router-01
   192.168.1.11,router-02
   ```

   Fields: `router_ip`, `hostname` (order doesn't matter, names are flexible: ip/address, name/router_name also work)

### Run Script

```bash
python3 compare_router_config.py
```

#### Single Router Mode

```
Enter path to template config file: router_config_template.txt
Single router or CSV mode? (s/c) [default: c]: s
Enter router hostname: router-01
Enter router IP address: 192.168.1.10
Enter SSH username: admin
Enter SSH password: ****
```

#### CSV Mode (default)

```
Enter path to template config file: router_config_template.txt
Single router or CSV mode? (s/c) [default: c]: c
Enter path to CSV file [default: routers.csv]: routers.csv
Enter SSH username: admin
Enter SSH password: ****
```

## Output

HTML reports are generated in the `reports/` directory with timestamp-based filenames:
```
reports/2026-09-12_14-30-45-router-01_comparison.html
reports/2026-09-12_14-30-58-router-02_comparison.html
```

Each report shows:
- **Compliance status** (COMPLIANT or VARIANCES FOUND)
- **Summary statistics** (template sections, missing, extra, differences)
- **Missing sections** - in template but not in router
- **Extra sections** - in router but not in template
- **Section diffs** - detailed line-by-line differences per section

## Logging

All operations logged to `logs/` directory:
```
logs/2026-09-12_14-30-45-compare_router_config.log
```

Logs include:
- Connection attempts and results
- Config retrieval status
- Comparison details
- Report generation status
- Summary of successes/failures

## Template Best Practices

1. **Voice-only sections**: Template focuses on voice config; non-voice sections in routers are ignored
2. **Partial configs OK**: Template doesn't need complete configuration; partial sections are checked
3. **Comments ignored**: Lines starting with `!` are skipped
4. **Indentation preserved**: Sub-commands under sections use indentation (matched in comparison)
5. **Examples**:
   - Include voice classes for codec validation
   - Include dial-peer definitions you want to enforce
   - Include voice-port settings for consistency checks
   - Can include multiple independent sections

## Troubleshooting

**Authentication failed**
- Verify SSH credentials and permissions
- Check router is accessible at IP address
- Ensure SSH is enabled on router

**Connection timeout**
- Increase timeout (default 15s) - edit script or adjust network
- Check network connectivity to router
- Verify router SSH port (default 22)

**CSV parsing errors**
- Ensure CSV has headers: `router_ip` (or `ip`, `address`) and `hostname` (or `name`, `router_name`)
- Check for extra spaces or special characters in CSV
- Verify file is plain text, not Excel format

**Missing sections in report**
- Verify template file path is correct
- Check template contains valid Cisco config syntax
- Ensure voice-related keywords are present (script filters for: voice, dial-peer, call-manager, etc.)

## Dependencies

- **netmiko**: SSH connection handler for network devices
- **pathlib, csv, logging**: Python standard library
- **difflib**: For line-by-line comparison (standard library)

## Notes

- Reports are self-contained HTML files (can be emailed/archived)
- Running config is retrieved but not saved (comparison only)
- SSH timeout default is 15 seconds (adequate for most routers)
- Script gracefully handles connection/auth failures per router (continues to next)
