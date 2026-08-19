#!/usr/bin/env python3
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from lxml import etree
import sys
import base64
import json
import os
import requests
from requests.adapters import HTTPAdapter
import urllib3
#from urllib3.util.ssl_ import DEFAULT_CIPHERS
from urllib3.util.retry import Retry


def findFiles(searchPath, searchPattern):
    """Used to find files that match the searchPattern

    Args:
        searchPath (string): Directory to seach
        searchPattern (string): Search pattern such as ccg-*.xml

    Returns:
        all_files: List of files that match the searchString
    """
    all_files = []
    all_files.extend(sorted(searchPath.glob(searchPattern)))
    return(all_files)


def loggerSetup(logPath):
    """Setup a custom logger to handle file and stdout logging.

    Args:
        logPath (string): Path to log file location.
    
    Returns:
        logger fully setup
    """
    # Create Logger and Set Level
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)

    # Set log message format
    messageFormat = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
    
    # Create CLI log handler
    stdoutHandler = logging.StreamHandler(sys.stdout)
    stdoutHandler.setFormatter(messageFormat)
    
    ## Create log file handler
    # Check if the need direcotry exists
    logSplit = str(logPath).rsplit('/', 1)
    # logSplit = str(logPath).rsplit('\\', 1)
    path_exists = os.path.isdir(logSplit[0])
    # If not Create log directory
    if path_exists == False:
        try:
            os.makedirs(logSplit[0])
        except OSError as e:
            print(f'Unable to create logging directory. Please check permissions\n {e}')      
    logFileHandler = RotatingFileHandler(logPath, maxBytes=500000, backupCount=5)
    logFileHandler.setFormatter(messageFormat)
    
    # Output logs to CLI and File
    logger.addHandler(logFileHandler)
    logger.addHandler(stdoutHandler)
    return(logger)


def serverSetup(json_file, usernameField, passwordField, serverField, versionField, serverType):
    """This takes in a json file and returns login information based on  server type

    Args:
        json_file (string): Full Path to a json file with login credentials.
        usernameField (string): Key to username in json file.
        passwordField (string): Key to password json file.
        serverField (string): Key to server in json file.
        versionField (string): Key to server version in json file. 
        requestType (string): 'api' returns base64 login info, 'non-api' return username and password.

    Returns:
        If serverType: cucm - username, password, server, version
        If serverType: uccx - server, base64_hash, version
    """
    # Open json file to read selected username, password, and server info
    with open(json_file) as json_data_file:
        logindata = json.load(json_data_file)

    # Set variables from the 'cucm-info.json' file
    username = logindata[usernameField]
    password = logindata[passwordField]
    server = logindata[serverField]
    version = logindata[versionField]

    if serverType.lower() == 'non-api':
        return(username, password, server, version)
    else:
        # Encode username and password to Base64
        message = f'{username}:{password}'
        message_bytes = message.encode('ascii')
        base64_bytes = base64.b64encode(message_bytes)
        base64_hash = base64_bytes.decode('ascii')
        return(server, base64_hash, version)


def httpSetup(version):
    """Setup HTTP session with disabled security warnings, and a retry srategy for limited http methods.
        Also if the server version is older than 10.6, we need to add in the deffie hellman cipher.

    Args:
        version (string): CUCM or UCCX server version

    Returns:
        http: The fully setup http session
    """
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    retryStrategy = Retry(total=3, status_forcelist=[429, 500, 502, 503, 504], method_whitelist=["HEAD", "GET", "OPTIONS", "POST"])
    adapter = HTTPAdapter(max_retries=retryStrategy)
    http = requests.session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    # # Fix for removed ciphers in older UCCX
    # if float(version) < 10.6:
    #     DEFAULT_CIPHERS += 'HIGH:!DH:!aNULL' # pylint: disable=undefined-variable
    return(http)