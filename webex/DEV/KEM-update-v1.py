""" Python Script to update KEM modules on phones in Control Hub
    
As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on: https://developer.webex.com/calling/docs/api/v1/

"""
__author__ = "Dan Fox"
__date__ = "2026/07/22"

#############  Imports  #############

import requests
import json
import time
import sys
import csv
from csv import reader
#used for settings.ini file:
import configparser
import os
import datetime

#############  Definitions  #############

bearerToken = ''
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
locationsUrl = 'https://webexapis.com/v1/locations'


# Set to True to enable debug messages
DEBUG_MODE = True

#############  Functions  #############

def dprint(*args, **kwargs):
    if DEBUG_MODE:
        print("[DEBUG]", *args, **kwargs)

def checkForData(data):
  if data:
    value = data
  else:
    value = ''
  return(value)  


