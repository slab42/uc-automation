import requests
import json
from csv import reader

bearerToken = 'NzdkZDIzNjktY2ZhZS00ZmQ1LTkyZjAtMjk5NjQ0MDFhNmQ2YTlhZmIyZmEtYzM5_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd'
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
extensionLookupUrl = 'https://webexapis.com/v1/telephony/config/numbers?extension='
locationsUrl = 'https://webexapis.com/v1/locations'
workspaceLocationsUrl = 'https://webexapis.com/v1/workspaceLocations?displayName='
createWorkspaceUrl='https://webexapis.com/v1/workspaces'


def getLocationID(name):
  response = requests.request("GET", locationsUrl + '?name=' + name, headers=defaultHeaders)
  if response.status_code == 200:
    if response.json()['items']:
      for location in response.json()['items']:
        locationID = location['id']
        return(locationID)
    else:
      print (f'ERROR: Invalid Location Name: {name}.')
  else:
    print(f'ERROR: Something went wrong retriving ID for {name}.')


def getWorkspaceLocationID(name):
  response = requests.request("GET", workspaceLocationsUrl + name, headers=defaultHeaders)
  if response.status_code == 200:
    if response.json()['items']:
      for location in response.json()['items']:
        locationID = location['id']
        return(locationID)
    else:
      print (f'ERROR: Invalid Location Name: {name}.')
  else:
    print(f'ERROR: Something went wrong retriving ID for {name}.')


def checkForData(data):
  if data:
    value = data
  else:
    value = ''
  return(value)


# Begin Script
print('This script requires two inputs:')
print('    1. An access token used to authorize the API calls\n       (You can get yours from https://developer.webex.com/docs/api/getting-started)\n')
print('    2. The full file path on your device for an input CSV file\n       (ex: C:\Scripts\huntAgents.csv on Windows or ~/Scripts/huntAgents.csv on Mac)\n')


# Loop to allow the user to input an access token until successful.
validationSuccess = 0
while (validationSuccess == 0):
    if not bearerToken :
        bearerToken = input('Please enter your access token:  ')
    # Get People API Call to validate access token.
    defaultHeaders = {
                'Authorization': 'Bearer ' + bearerToken 
                }
    validationResponse = requests.get(getMyDetailsURL, headers=defaultHeaders, timeout=3)
    if validationResponse.status_code == 401:
        # This means the access token was invalid.
        print('Access Token was invalid.  Please check your access token was entered correctly and hasn\'t expired and try again below.\n')
        bearerToken = ''
    else:
        validationSuccess = 1
print('Access Token validated succesfully.\n')


# Read the CSV in and create the hunt group.
input_file = input('Enter CSV file name or full path: ')
with open(input_file, 'r', encoding='utf8') as my_file:
    csv_file = reader(my_file)
    next(my_file)
    for index, row in enumerate(csv_file, start=2):
        name = checkForData(row[0])
        workspaceLocationId = getWorkspaceLocationID(row[1])
        workspaceType = checkForData(row[2])
        phoneNumberinput = checkForData(row[3])
        if phoneNumberinput == '':
           pass # Do nothing
        else:
           phoneNumber = '+' + phoneNumberinput
        extension = checkForData(row[4])
        locationId = getLocationID(row[5])
       
        if name:
            if phoneNumber:
                payload = json.dumps({
                "displayName": name,
                "workspaceLocationId": workspaceLocationId,
                "type": workspaceType,
                "calling": {
                    "type": "webexCalling",
                    "webexCalling": {
                        "phoneNumber": phoneNumber,
                        "extension": extension,
                        "locationId": locationId
                        }
                    },
                })
            else:
               payload = json.dumps({
                "displayName": name,
                "workspaceLocationId": workspaceLocationId,
                "type": workspaceType,
                "calling": {
                    "type": "webexCalling",
                    "webexCalling": {
                        "extension": extension,
                        "locationId": locationId
                        }
                    },
                })

            # Create Workspace
            headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + bearerToken 
            }

            response = requests.request("POST", createWorkspaceUrl, headers=headers, data=payload, timeout=10)

            if response.status_code != 201:
                print(f'ERROR: Row {index}, Response Code: {response.status_code}\n {response.text}')
            else:
                print(f'INFO: Workspace Created Successfully: {name}.')

        else:
            print(f'ERROR: Incomplete data in row {index}.')
    
