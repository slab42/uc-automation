#!/usr/bin/env python3
"""
Environment loader for customer configuration and credentials.
Loads customer_env.json with email/alert settings.
Loads credentials.env with CUCM, CUC, CUBE, and Webex credentials.
"""

import json
import configparser
import getpass
from pathlib import Path


class EnvironmentConfig:
    """Loads and manages customer configuration."""

    def __init__(self, config_path=".env/customer_env.json"):
        """Initialize environment config. Looks for customer_env.json in .env folder."""
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

    def get_console_log_level(self):
        """Get console logging level from config. Defaults to 'INFO'."""
        logging_config = self.config.get('logging', {})
        return logging_config.get('console_log_level', 'INFO')


class CredentialsLoader:
    """Loads and manages credentials from credentials.env file."""

    def __init__(self, creds_path=".env/credentials.env"):
        """Initialize credentials loader. Looks for credentials.env in .env folder."""
        self.creds_path = Path(__file__).parent.parent / creds_path
        self.config = configparser.ConfigParser()
        self._load_credentials()

    def _load_credentials(self):
        """Load credentials from INI-style credentials.env file."""
        if not self.creds_path.exists():
            return

        try:
            self.config.read(self.creds_path)
        except configparser.Error as e:
            print(f"ERROR: Failed to parse {self.creds_path.name}: {e}")

    def get_cucm_credentials(self, cluster_name=None):
        """
        Get CUCM cluster credentials.
        If cluster_name is None, returns a list of all available clusters.
        If cluster_name is specified, returns credentials for that cluster.
        """
        sections = [s for s in self.config.sections() if s.startswith('CUCM:')]

        if not sections:
            return None if cluster_name else []

        if cluster_name is None:
            # Return list of all CUCM clusters
            clusters = []
            for section in sections:
                cluster_id = section.split(':', 1)[1]
                clusters.append(self._get_section_as_dict(section, cluster_id))
            return clusters

        # Return specific cluster
        section = f"CUCM:{cluster_name}"
        if self.config.has_section(section):
            return self._get_section_as_dict(section, cluster_name, prompt_password=True)
        return None

    def get_cuc_credentials(self, cluster_name=None):
        """
        Get CUC cluster credentials.
        If cluster_name is None, returns a list of all available clusters.
        """
        sections = [s for s in self.config.sections() if s.startswith('CUC:')]

        if not sections:
            return None if cluster_name else []

        if cluster_name is None:
            clusters = []
            for section in sections:
                cluster_id = section.split(':', 1)[1]
                clusters.append(self._get_section_as_dict(section, cluster_id))
            return clusters

        section = f"CUC:{cluster_name}"
        if self.config.has_section(section):
            return self._get_section_as_dict(section, cluster_name, prompt_password=True)
        return None

    def get_cube_credentials(self, device_name=None):
        """
        Get CUBE device credentials.
        If device_name is None, returns a list of all available devices.
        """
        sections = [s for s in self.config.sections() if s.startswith('CUBE:')]

        if not sections:
            return None if device_name else []

        if device_name is None:
            devices = []
            for section in sections:
                device_id = section.split(':', 1)[1]
                devices.append(self._get_section_as_dict(section, device_id))
            return devices

        section = f"CUBE:{device_name}"
        if self.config.has_section(section):
            return self._get_section_as_dict(section, device_name, prompt_password=True)
        return None

    def get_webex_credentials(self, cluster_name=None):
        """
        Get Webex cluster credentials.
        If cluster_name is None, returns a list of all available clusters.
        """
        sections = [s for s in self.config.sections() if s.startswith('WEBEX:')]

        if not sections:
            return None if cluster_name else []

        if cluster_name is None:
            clusters = []
            for section in sections:
                cluster_id = section.split(':', 1)[1]
                clusters.append(self._get_section_as_dict(section, cluster_id))
            return clusters

        section = f"WEBEX:{cluster_name}"
        if self.config.has_section(section):
            return self._get_section_as_dict(section, cluster_name)
        return None

    def _get_section_as_dict(self, section, identifier, prompt_password=False):
        """Convert a config section to a dictionary, optionally prompting for password."""
        creds = {}
        for key, value in self.config.items(section):
            creds[key] = value

        # Add identifier for reference
        creds['identifier'] = identifier

        # If password is blank and we should prompt, ask user
        if prompt_password and 'password' in creds and not creds['password']:
            service_type = section.split(':')[0]
            prompt_text = f"Enter password for {service_type} '{identifier}': "
            creds['password'] = getpass.getpass(prompt_text)

        return creds

    def list_credentials(self, service_type=None):
        """
        List all available credentials.
        If service_type is None, lists all.
        service_type can be 'CUCM', 'CUC', 'CUBE', or 'WEBEX'.
        """
        if service_type is None:
            return self.config.sections()

        return [s for s in self.config.sections() if s.startswith(f"{service_type}:")]
