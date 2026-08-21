""" Python Script to foward Workspace numbers in Control Hub
    
1) Input is List of users' & numbers

userId,extension,phoneNumber
user1,,12704435531
user2,,12704435532

As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on: https://developer.webex.com/calling/docs/api/v1/numbers/add-phone-numbers-to-a-location

"""
__author__ = "Dan Fox"
__date__ = "2026/07/31"

#############  Imports  #############

import requests
import json
import os
from csv import reader
import configparser
import os


bearerToken = 'NzdkZDIzNjktY2ZhZS00ZmQ1LTkyZjAtMjk5NjQ0MDFhNmQ2YTlhZmIyZmEtYzM5_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd'
forwardPrefix = '88888888'

displayName = ''
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
workspaceURL = 'https://webexapis.com/v1/workspaces'


# Set to True to enable debug messages
DEBUG_MODE = False


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

############. Get User ID from email address:
def getWorkspaceID(displayName):
    url = workspaceURL + '?displayName=' + displayName 
    dprint(f'URL: {url}')

    response = requests.request("GET", url, headers=defaultHeaders)
    if response.status_code == 200:
        if response.json()['items']:
            for workspace in response.json()['items']:
                workspaceID = workspace['id']
                return(workspaceID)
        else:
            print(f'ERROR: Invalid User Name: {displayName}.')
            print(f'ERROR: Response Code: {response.status_code}\n {response.text}')
    else:
        print(f'ERROR: Something went wrong retriving ID for {displayName}.')        

def callForwardAllWorkspace(workspaceID,forwardNumber):
    payload = json.dumps({
        "callForwarding": {
            "always": {
                "enabled": True,
                "destination": f"{forwardNumber}"
            }
        }
    })
    dprint(f'payload is: {payload}')

    headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + bearerToken 
    }
    response = requests.request('PUT', workspaceURL + '/' + workspaceID + '/features/callForwarding', headers=headers, data = payload)
    dprint(response.text.encode('utf8'))
    return(response)



####### testing:

defaultHeaders = {
        'Authorization': 'Bearer ' + bearerToken 
        }
    

displayName = 'Test Workspace'



workspaceID = getWorkspaceID(displayName)

print(f'displayName id is: {workspaceID}')

#forwardNumber = 

workspaceForward = callForwardAllWorkspace(workspaceID,forwardNumber)