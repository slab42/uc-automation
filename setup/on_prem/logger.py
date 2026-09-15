#!/usr/bin/env python3
import warnings
warnings.simplefilter('ignore')

import logging
from logging.handlers import RotatingFileHandler
import sys
import os


def setup_logger(log_path):
    """Setup a dual-output logger (stdout and file) with rotating file handler.

    Args:
        log_path (str): Full path to log file location.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)

    message_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler(sys.stdout)
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
