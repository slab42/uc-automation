""" Python Script to Call Forward numbers on any Calling item in Control Hub
    
This script is designed to call forward numbers on multiple owner types (AA, HG, Person, etc.) in Control Hub organization based on an INPUT CSV file.
Variable at the top of the script for forwardPrefix.   This prefix number is added to the front of the phone number and applied as the forward destination.
The script is designed to be executed by users with "full admin" role in the org.

Tested with Python version 3.11.66


1) CSV should be list of phone numbers, can be PSTN or extension:
-Phone numbers must be existing in Control Hub

phoneNumber
12704435531
12704435532

As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on: https://developer.webex.com/calling/docs/api/v1/numbers/add-phone-numbers-to-a-location

"""
__author__ = "Dan Fox"
__date__ = "2026/08/01"

#############  Imports  #############

import requests
import json
from csv import reader
#used for settings.ini file:
import configparser
import os

#############  Definitions  #############


bearerToken = ''
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
forwardPrefix = '88888888'
locationID = ''

invalidOwner = False
workspaceURL = 'https://webexapis.com/v1/workspaces'
virtuallineURL = 'https://webexapis.com/v1/telephony/config/virtualLines'
peopleURL = 'https://webexapis.com/v1/people'
telephonyURL = 'https://webexapis.com/v1/telephony/config/locations'

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


def getPhoneNumber(phoneNumber):
    url = "https://webexapis.com/v1/telephony/config/numbers?phoneNumber=" + phoneNumber
    payload = None

    response = requests.request('GET', url, headers=defaultHeaders, data = payload)
    if response.status_code == 200:
        if response.json()['phoneNumbers']:
            data = response.json()
            dprint(data)
            locationID = data['phoneNumbers'][0]['location']['id']
            ownerType = data['phoneNumbers'][0]['owner']['type']
            ownerID = data['phoneNumbers'][0]['owner']['id']
            return(locationID,ownerType,ownerID)
        else:
            print(f'ERROR: Invalid phone number: {phoneNumber}.')
            dprint(f'ERROR: Response Code: {response.status_code}\n {response.text}')
    else:
        print(f'ERROR: Something went wrong retriving info for {phoneNumber}.')      


def callForwardAll(locationID,ownerType,forwardNumber):
    global invalidOwner
    ### Person:
    if ownerType == 'PEOPLE':
        url = peopleURL + '/' + ownerID + '/features/callForwarding'
    ### Workspace:
    elif ownerType == 'PLACE':
        url = workspaceURL + '/' + ownerID + '/features/callForwarding'
    ### Workspace:
    elif ownerType == 'VIRTUAL_LINE':
        url = virtuallineURL + '/' + ownerID + '/callForwarding'
    elif ownerType == 'HUNT_GROUP':
        url = telephonyURL + '/' + locationID + '/huntGroups/' + ownerID + '/callForwarding'
    elif ownerType == 'CALL_QUEUE':
        url = telephonyURL + '/' + locationID + '/queues/' + ownerID + '/callForwarding'
    elif ownerType == 'AUTO_ATTENDANT':
        url = telephonyURL + '/' + locationID + '/autoAttendants/' + ownerID + '/callForwarding'
    else:
        print(f'ERROR: ownerType is not configured, {ownerType}')
        invalidOwner = 'Yes'

    dprint(f'Invalid owner is set to: {invalidOwner}')
    if invalidOwner == 'Yes':
        ## invalid owner type.  Moving on.
        dprint(f'Invalid ownerType, skipping forward attempt.')
        pass
    else:
        ## Virtual Line required businessContinity in payload vs all others:
        if ownerType == 'VIRTUAL_LINE':
            payload = json.dumps({
                "callForwarding": {
                    "always": {
                        "enabled": True,
                        "destination": f"{forwardNumber}"
                    }
                },
                "businessContinuity": {
                    "enabled": True,
                    "destination": f"{forwardNumber}"
                }
                })
        # elif ownerType == 'HUNT_GROUP' or ownerType == 'CALL_QUEUE' or ownerType == 'AUTO_ATTENDANT':
        #     payload = json.dumps({
        #         "callForwarding": {
        #             "always": {
        #                 "enabled": True,
        #                 "destination": f"{forwardNumber}"
        #             }#,
        #             # "operatingModes": { "modes": [] }
        #         },
        #         })        
        else:
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
        response = requests.request('PUT', url, headers=headers, data = payload)
        dprint(response.text.encode('utf8'))
        return(response)


################## Main Script:


############ Begin Script #######################
print('This script requires two inputs:')
print('    1. An access token used to authorize the API calls\n       (You can get yours from https://developer.webex.com/docs/api/getting-started)\n')
print('    2. The full file path on your device for an input CSV file\n       (ex: C:\Scripts\huntAgents.csv on Windows or ~/Scripts/huntAgents.csv on Mac)\n')

# Check for settings.ini file and setting token:
if not bearerToken :
    if os.path.isfile("settings.ini"):
        dprint("settings.ini file exists")
        config = configparser.ConfigParser()
        config.read('settings.ini')
        try:
            bearerToken = config ['access']['bearerToken']
        except:
            dprint("Issue with accessing the settings.ini - bearerToken.")
            bearerToken = ''
        # else:
        #     bearerToken = ''
        dprint(f'BearerToken is: {bearerToken}')
    else:
        print("No settings.ini file found, moving on.")

# Loop to allow the user to input an access token until successful.
validationSuccess = 0
while (validationSuccess == 0):

    ### Request bearerToken if not present:
    if not bearerToken :
        bearerToken = input('Please enter your access token:  ')

    defaultHeaders = {
            'Authorization': 'Bearer ' + bearerToken 
            }
    # Get People API Call to validate access token.
    validationResponse = requests.get(getMyDetailsURL, headers=defaultHeaders, timeout=3)
    if validationResponse.status_code == 401:
        # This means the access token was invalid.
        print('Access Token was invalid.  Please check your access token was entered correctly and hasn\'t expired and try again below.\n')
        bearerToken = ''
    else:
        validationSuccess = 1
print('Access Token validated succesfully.\n')

### Read the CSV in.
input_file = input('Enter CSV file name or full path: ')
#input_file = './numbers-lean.csv' ####. Hard setting used for testing only


with open(input_file, 'r', encoding='utf-8-sig') as my_file:
    csv_file = reader(my_file)
    first_row = next(csv_file)
    dprint(f'Headers are: {first_row}')

    for index, row in enumerate(csv_file, start=2):
        phoneNumber = checkForData(row[0])
        phoneNumberInfo = getPhoneNumber(phoneNumber)
        dprint(f'PhoneNumber entry is: {phoneNumber}')
        dprint(f'phoneNumberInfo is: {phoneNumberInfo}')
        if phoneNumberInfo is None:
            # Was in valid phone number
            dprint(f'phoneNumberInfo is: None')
        else:
            dprint(f'phoneNumberInfo is: valid')
            locationID = (phoneNumberInfo[0])
            ownerType = (phoneNumberInfo[1])
            ownerID = (phoneNumberInfo[2])
            dprint(f'Location is: {locationID}, ownerType is: {ownerType}, ownerID is: {ownerID}')

            if phoneNumber:
                forwardNumber = forwardPrefix + phoneNumber
                dprint(f'Forward Number is set to: {forwardNumber}')
                forwardThisNumber = callForwardAll(locationID,ownerType,forwardNumber)

                if forwardThisNumber.status_code != 204:
                    print(f'ERROR: Row {index}, Response Code: {forwardThisNumber.status_code}\n {forwardThisNumber.text}')
                else:
                    print(f'INFO: Phone number {phoneNumber} successfully set to CFA to {forwardNumber}.')


            else:
                print(f'ERROR: Incomplete data in row {index}.')

### End script:
print(f'INFO: End of script')
