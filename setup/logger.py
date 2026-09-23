#!/usr/bin/env python3
import warnings
warnings.simplefilter('ignore')

import logging
from logging.handlers import RotatingFileHandler
import sys
import os
from pathlib import Path


def setup_logger(log_path):
    """Setup a dual-output logger (stdout and file) with rotating file handler.

    Args:
        log_path (str): Full path to log file location.

    Returns:
        logging.Logger: Configured logger instance.

    Configuration (in order of precedence):
        1. CONSOLE_LOG_LEVEL environment variable
        2. logging.console_log_level in customer_env.json
        3. Default: INFO
    """
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)

    message_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

    # Determine console log level: env var > config file > default
    console_level_str = os.getenv('CONSOLE_LOG_LEVEL')

    if not console_level_str:
        try:
            from env_loader import EnvironmentConfig
            config = EnvironmentConfig()
            console_level_str = config.get_console_log_level()
        except Exception:
            console_level_str = 'INFO'

    console_level_str = console_level_str.upper()
    console_level = getattr(logging, console_level_str, logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(console_level)
    stdout_handler.setFormatter(message_format)

    log_dir = str(log_path).rsplit('/', 1)[0]
    if not os.path.isdir(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            print(f'Unable to create logging directory. Please check permissions\n {e}')

    log_file_handler = RotatingFileHandler(log_path, maxBytes=500000, backupCount=5)
    log_file_handler.setFormatter(message_format)

    logger.addHandler(log_file_handler)
    logger.addHandler(stdout_handler)
    return logger
