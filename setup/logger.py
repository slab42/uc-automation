#!/usr/bin/env python3
import warnings
warnings.simplefilter('ignore')

import logging
from logging.handlers import RotatingFileHandler
import sys
import os
from pathlib import Path



def setup_logger(log_path, debug=False):
    """Setup a dual-output logger (stdout and file) with rotating file handler.

    Args:
        log_path (str): Full path to log file location.
        debug (bool): If True, set console log level to DEBUG. Otherwise defaults to INFO.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)

    message_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

    console_level = logging.DEBUG if debug else logging.INFO

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
