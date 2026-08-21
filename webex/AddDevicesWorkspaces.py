""" Python Script to add Devices (on Workspaces) in Control Hub
    
As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on: https://developer.webex.com/calling/docs/api/v1/numbers/add-phone-numbers-to-a-location

"""
__author__ = "Dan Fox"
__date__ = "2026/07/22"

#############  Imports  #############
import requests
import json

#############  Definitions  #############

bearerToken = ''
getMyDetailsURL = 'https://webexapis.com/v1/people/me'

workspaceURL = 'https://webexapis.com/v1/workspaces'
peopleURL = 'https://webexapis.com/v1/people'

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


### Add Device to workspace:

def addDevice(workspaceID, model, mac):
    url = "https://webexapis.com/v1/devices"
    payload = json.dumps({
        "mac": mac,
        "model": model,
        "workspaceId": workspaceID
    })
    dprint(f'payload is: {payload}')    
    headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + bearerToken, "Accept": "application/json"}
    response = requests.request('POST', url, headers=headers, data = payload)
    dprint(response.text.encode('utf8'))
    return(response)


# Begin Script
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



with open(input_file, 'r', encoding='utf-8-sig') as my_file:
    csv_file = reader(my_file)
    first_row = next(csv_file)
    dprint(f'Headers are: {first_row}')


    for index, row in enumerate(csv_file, start=2):
        locationName = checkForData(row[0])
        locationId = getLocationID(row[0])
        model = checkForData(row[1])
        mac = checkForData(row[2])

