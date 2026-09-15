# Customer Environment Configuration

## Setup

1. Copy the example file from project root:
   ```bash
   cp customer_env.json.EXAMPLE customer_env.json
   ```
   (Located in the project root, not in the cube folder)

2. Edit `customer_env.json` with your environment values:
   - **mail_server** - Your SMTP server hostname
   - **mail_port** - SMTP port (usually 25 or 587)
   - **source_email** - Sender email address
   - **destination_email** - Where to send alerts
   - **low_memory_threshold** - Alert when free memory drops below this percentage

3. Add to .gitignore:
   ```bash
   echo "customer_env.json" >> .gitignore
   ```

## Example Configuration

```json
{
  "email": {
    "mail_server": "mail.example.com",
    "mail_port": 25,
    "source_email": "cube-alerts@example.com",
    "destination_email": "ops-team@example.com"
  },
  
  "router_memory_check": {
    "low_memory_threshold": 33
  }
}
```

## What Gets Configured

- **Email alerts** - mail server and recipient addresses
- **Memory threshold** - What percentage triggers a low memory alert

Other settings like SSH port (22) and timeouts remain in the scripts as they're technical defaults.

## Scripts Using This Config

- `check_router_mem_status.py` - Uses email config and memory threshold

## Without the Config File

Scripts will work fine with default values if `customer_env.json` doesn't exist. Copy and customize the .EXAMPLE file only when you need different values than the defaults.
