""" 
CURRENTLY STILL IN DEV.   ISSUES MIGRATING NUMBERS DIRECTLY IN CH AND API IS STILL BETA.
WORKING on GA for Standard to ELIN.   No other migrations are functional currently.

Python Script to Modify PSTN numbers on a location in Control Hub
    
This script is designed to add numbers with in a locaiton into Control Hub organization based on an INPUT CSV file.
The script is designed to be executed by users with "full admin" role in the org.

Tested with Python version 3.11.66

Two CSV formats are supported:

1) Lite version, all numbers are entered as DID and actived:
-Locations must be existing in Control Hub
-Script is built to add "+" at beginning of phoneNumbers to alleviate excel issues.

locationId,phoneNumber
Location1,12704435531
Location2,12704435532

2) Full version, used for "AddNumbersToLocation.py":
-Locations must be existing in Control Hub
-Script is built to add "+" at beginning of phoneNumbers to alleviate excel issues.
-Numbers must be added into CH first.
- Modify may be "Elin", "Standard", or "Service"
    - When left blank the script will skip modifying this number.

locationId,phoneNumber,numberType,numberUsageType,state,modify
Location1,12704435531,DID,NONE,ACTIVE,
Location2,12704435532,DID,NONE,ACTIVE,Elin


As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on: https://developer.webex.com/calling/docs/api/v1/numbers/add-phone-numbers-to-a-location

"""
__author__ = "Dan Fox"
__date__ = "2026/07/22"

#############  Imports  #############
import requests
import json
import time
import sys
from csv import reader

#############  Definitions  #############

#bearerToken = 'MjRlMTdkMjQtMTljYS00ZDI2LTg2M2MtMTFjODc0ZWEzODcxMzdkNmY5NTYtZGJm_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd'
bearerToken = ''

getMyDetailsURL = 'https://webexapis.com/v1/people/me'
locationsUrl = 'https://webexapis.com/v1/locations'
callingLocaitonURL = 'https://webexapis.com/v1/telephony/config/locations'
pstnLocationsURL = 'https://webexapis.com/v1/telephony/pstn/locations/'

# Set to True to enable debug messages
DEBUG_MODE = True


#############  Functions  #############

def dprint(*args, **kwargs):
    if DEBUG_MODE:
        print("[DEBUG]", *args, **kwargs)

def getLocationID(name):
  response = requests.request("GET", locationsUrl + '?name=' + name, headers=defaultHeaders)
  if response.status_code == 200:
    if response.json()['items']:
      for location in response.json()['items']:
        locationID = location['id']
        return(locationID)
    else:
      print (f'ERROR: Invalid Calling Location Name: {name}.')
  else:
    print(f'ERROR: Something went wrong retriving ID for {name}.')


def getCallingLocationID(name):
  response = requests.request("GET", callingLocaitonURL + '?name=' + name, headers=defaultHeaders)
  dprint(f'{response.status_code}')
  if response.status_code == 200:
    if response.json()['locations']:
      for location in response.json()['locations']:
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
#input_file = './numbers-lean.csv'

start_time = time.time()

### Count the number of entries found in the CSV file, if row count=0 end script:
with open(input_file, 'r', encoding='utf8') as my_file:
    csv_file = reader(my_file)
    try:
        first_row = next(csv_file)
        num_rows = sum(1 for row in csv_file)
        print(f'INFO: Number of rows in CSV is: {num_rows}')
        if num_rows == 0:
           print(f'ERROR: Numbers of rows is: {num_rows}.  Ending script.\n')
           exit()
    except csv.Error as e:
        sys.exit(f'file {input_file}, line {reader.line_num}: {e}')


with open(input_file, 'r', encoding='utf8') as my_file:
    csv_file = reader(my_file)
    first_row = next(csv_file)
    dprint(f'Headers are: {first_row}')

    num_columns = len(first_row)
    dprint(f'Number of columns in CSV is: {num_columns}')

    for index, row in enumerate(csv_file, start=2):
        locationId = getCallingLocationID(row[0])
        dprint(f'locationId: {locationId}')
        phoneNumber = checkForData(row[1])
        
        if num_columns == 3:
           modify = checkForData(row[2])
           
        else: # CSV columns = 6
           modify = checkForData(row[5])

        if phoneNumber:
            if modify:
               ## ELIN / SERVICE / STANDARD
                print(f'INFO: Modify request for {phoneNumber}'),
                payload = json.dumps({
                "numbers": [f" +{phoneNumber} "]
                })
                
                dprint(f'payload is: {payload}')

                # Start Modify Phone Number
                headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + bearerToken 
                }

                print(f'INFO: phoneNumber: {phoneNumber}, locationID: {locationId}, and modify: {modify}')
                addNumberUrl = pstnLocationsURL + locationId + '/numbers?action=modify' + modify

                response = requests.request("POST", addNumberUrl, headers=headers, data=payload, timeout=10)
                dprint(f'response: {response}')
                dprint(f'ERROR: Row {index}, Response Code: {response.status_code}\n {response.text}')

                if response.status_code != 200:
                    print(f'ERROR: Row {index}, Response Code: {response.status_code}\n {response.text}')
                else:
                    print(f'INFO: Phone number {phoneNumber} successfully modified.')

            else:
                print(f'ERROR: Incomplete data in row {index}.')



        else: # Modify is empty, skipping
            print(f'INFO: No Modify request for {phoneNumber}'),

end_time = time.time()
execution_time = end_time - start_time
print(f"INFO: Execution time: {execution_time:.4f} seconds.")



