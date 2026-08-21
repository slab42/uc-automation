""" Python Script to foward users numbers in Control Hub
    
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


bearerToken = 'OTM5MmU3MDktMTVhZC00NzExLWEzZGUtZjk1MjM1NTBhOGEyMTNmZjRhNzUtZDZl_PF84_740bb8c4-0bd2-4f31-ad74-305a31d698d7'
forwardPrefix = '88888888'

userEmail = ''
domain = ''
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
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

############. Get User ID from email address:
def getUserID(userName):
    response = requests.request("GET", peopleURL + '?email=' + userName + '%40' + domain, headers=defaultHeaders)
    if response.status_code == 200:
        if response.json()['items']:
            for user in response.json()['items']:
                userID = user['id']
                return(userID)
        else:
            print (f'ERROR: Invalid User Name: {userName}.')
    else:
        print(f'ERROR: Something went wrong retriving ID for {userName}.')        

############ Call Forward all on User:
def callForwardAllPerson(userID,forwardNumber):
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
    response = requests.request('PUT', peopleURL + '/' + userID + '/features/callForwarding', headers=headers, data = payload)
    dprint(response.text.encode('utf8'))
    return(response)


#######


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

# ### Count the number of entries found in the CSV file, if row count=0 end script:
# with open(input_file, 'r', encoding='utf-8-sig') as my_file:
#     csv_file = reader(my_file)
#     try:
#         first_row = next(csv_file)
#         num_rows = sum(1 for row in csv_file)
#         print(f'INFO: Number of rows in CSV is: {num_rows}')
#         if num_rows == 0:
#            print(f'ERROR: Numbers of rows is: {num_rows}.  Ending script.\n')
#            exit()
#     except csv.Error as e:
#         sys.exit(f'file {my_file}, line {reader.line_num}: {e}')


with open(input_file, 'r', encoding='utf-8-sig') as my_file:
    csv_file = reader(my_file)
    first_row = next(csv_file)
    dprint(f'Headers are: {first_row}')


    for index, row in enumerate(csv_file, start=2):
        userEmail = checkForData(row[0])
        dprint(f'userEmail is: {userEmail}')
        userNumber = checkForData(row[1])
        dprint(f'userNumber is: {userNumber}')
        userName, domain = userEmail.split('@', 1)
        forwardNumber = forwardPrefix + userNumber
        
        print(f'INFO: {userName} Starting forward to number: {forwardNumber}')

        userID = getUserID(userName)
        dprint(f'UserID is: {userID}')

        forwardThisNumber = callForwardAllPerson(userID,forwardNumber)
        if forwardThisNumber.text == '':
            print(f'INFO: {userName} forwarded successfully.')
        else:
            print(f'ERROR: {userName} forwarded FAILED.')
            print(forwardThisNumber.text.encode('utf8'))



