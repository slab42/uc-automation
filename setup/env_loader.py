#!/usr/bin/env python3
"""
Simple environment loader for customer-specific configuration.
Loads customer_env.json with email and alert settings.
"""

import json
from pathlib import Path


class EnvironmentConfig:
    """Loads and manages customer configuration."""

    def __init__(self, config_path="customer_env.json"):
        """Initialize environment config. Looks for customer_env.json in project root."""
        self.config_path = Path(__file__).parent.parent / config_path
        self.config = self._load_config()

    def _load_config(self):
        """Load configuration from JSON file. Returns empty dict if file not found."""
        if not self.config_path.exists():
            return {}

        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse {self.config_path.name}: {e}")
            return {}
        except Exception as e:
            print(f"ERROR: Failed to load {self.config_path.name}: {e}")
            return {}

    def get_email_config(self):
        """Get email configuration with defaults."""
        email_config = self.config.get('email', {})
        return {
            'mail_server': email_config.get('mail_server', 'mail.slab42.net'),
            'mail_port': email_config.get('mail_port', 25),
            'source_email': email_config.get('source_email', 'cube-automation@slab42.net'),
            'destination_email': email_config.get('destination_email', 'alerts@slab42.net'),
        }

    def get_memory_threshold(self):
        """Get low memory threshold for alerts."""
        memory_config = self.config.get('router_memory_check', {})
        return memory_config.get('low_memory_threshold', 33)
