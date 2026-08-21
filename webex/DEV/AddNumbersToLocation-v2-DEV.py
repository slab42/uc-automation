""" Python Script to add PSTN numbers to a location in Control Hub
    
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

2) Full version, full customization of the import:
-Locations must be existing in Control Hub
-Script is built to add "+" at beginning of phoneNumbers to alleviate excel issues.
- numberType = TOLLFREE, DID (Script does NOT currently support MOBILE)
- numberUsageType = NONE (standard usage, default), SERVICE (high-volumne such as CC)
- state = ACTIVE (number is activated and has calling capability), INACTIVE (number is not yet activated and has no calling capability.)

locationId,phoneNumber,numberType,numberUsageType,state
Location1,12704435531,DID,NONE,ACTIVE
Location2,12704435532,DID,NONE,ACTIVE


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
country = 'US'



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
 

### Writing out failure entries:
# Initialize failures file:
failedImportFilePrefix = "AddNunmbers_failed_"
fileTimestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
dprint(f'fileTimestamp for failures is: {fileTimestamp}')
failed_import_file = failedImportFilePrefix + fileTimestamp + '.csv'
dprint(f'failed import filename is: {failed_import_file}')

def logFailureEntry(locationId, phoneNumber, numberTyp = '', numberUsageType = '', state = '', errorCause = ''):
    dprint(f'logFailureEntry function called.')
    try:
        with open(failed_import_file, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            
            # Write headers if it is a brand new file
            if file.tell() == 0:
                writer.writerow(first_row)
                
            # Append the error details
            dprint(f'Writing failed entry into Failed Import file.')
            writer.writerow([locationId, phoneNumber, numberType, numberUsageType, state, errorCause])
    except:
        print(f'[ERROR] Writing entry into failed imports file FAILED.')


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

start_time = time.time()

### Count the number of entries found in the CSV file, if row count=0 end script:
with open(input_file, 'r', encoding='utf-8-sig') as my_file:
    csv_file = reader(my_file)
    try:
        first_row = next(csv_file)
        num_rows = sum(1 for row in csv_file)
        print(f'INFO: Number of rows in CSV is: {num_rows}')
        if num_rows == 0:
           print(f'ERROR: Numbers of rows is: {num_rows}.  Ending script.\n')
           exit()
    except csv.Error as e:
        sys.exit(f'file {my_file}, line {reader.line_num}: {e}')


with open(input_file, 'r', encoding='utf-8-sig') as my_file:
    csv_file = reader(my_file)
    first_row = next(csv_file)
    dprint(f'Headers are: {first_row}')

    shouldBeHeaders = ['locationId', 'phoneNumber', 'numberType', 'numberUsageType', 'state', 'modify']
    if first_row == shouldBeHeaders:
       dprint(f'Headers match.')
    else:
       dprint(f'Headers do not match, validate source CSV file against script instructions.')

    num_columns = len(first_row)
    dprint(f'Number of columns in CSV is: {num_columns}')


    for index, row in enumerate(csv_file, start=2):
        locationName = checkForData(row[0])

        #### Need to write out to log failure entries if locationId fails on function:
        locationId = getLocationID(row[0])
        phoneNumber = checkForData(row[1])

        if num_columns == 2 or num_columns == 3:
            numberType = 'DID'
            numberUsageType = 'NONE'
            state = 'ACTIVE'        
        else:
            numberType = checkForData(row[2])
            numberUsageType = checkForData(row[3])
            state = checkForData(row[4])

        # if phoneNumber is entered as 10D, convert to 11:
        phoneNumberLen = len(phoneNumber)
        dprint(f'phoneNumberLen is {phoneNumberLen}')
        if country == 'US' and phoneNumberLen == 10:
            dprint('Phone number is only 10D, prefixing 1')
            phoneNumber = '1' + phoneNumber
            dprint('New phonenumber: {phoneNumber}')
        elif country == 'US' and phoneNumberLen <= 9:
            print('[ERROR] Phone number {phoneNumber}is less than 10D, will error out. Review')
            logFailureEntry(locationName, phoneNumber, numberType, numberUsageType, state)

        ### Check if locationId is None, if so then log out entry:
        if not locationId:
           locationId = checkForData(row[0])
           print(f'[ERROR] Current entry -- locationName: {locationName} and phoneNumber: {phoneNumber}.  Review.')
           logFailureEntry(locationName, phoneNumber, numberType, numberUsageType, state)
        else:    


            if phoneNumber:
                print(f'INFO: Starting creation of {phoneNumber}'),

                payload = json.dumps({
                # Example input: "phoneNumbers": [ "+12704435532" ],
                # CSV file is configure with 1+10D
                "phoneNumbers": [f" +{phoneNumber} "],
                "numberType": numberType,
                "numberUsageType": numberUsageType,
                "state": state
                })

                ### Print statement for outputing payload for debugging:
                dprint(f'payload is: {payload}')

                # Create Phone Number
                headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + bearerToken 
                }

                dprint(f'Info for request: phoneNumber: {phoneNumber} and locationID: {locationId}')
                addNumberUrl = 'https://webexapis.com/v1/telephony/config/locations/' + locationId + '/numbers'

                response = requests.request("POST", addNumberUrl, headers=headers, data=payload, timeout=10)

                if response.status_code != 200:
                    print(f'ERROR: Row {index}, Response Code: {response.status_code}\n {response.text}')
                else:
                    print(f'INFO: Phone number {phoneNumber} successfully created.')

            else:
                print(f'ERROR: Incomplete data in row {index}.')
                logFailureEntry(locationId, phoneNumber, numberType, numberUsageType, state)


### End script:
end_time = time.time()
execution_time = end_time - start_time
print(f"INFO: Execution time: {execution_time:.4f} seconds.")



