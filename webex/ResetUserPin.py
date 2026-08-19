import requests
# import json
from csv import reader

# bearerToken = 'NzExYWJlZTEtMDU3ZC00ZTQ1LWFkMTktNjk1Y2Q2Mjk5NDM4MGQwYmYwNzktZWZk_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd'
bearerToken = ''
userIDs = []
callingLicenseIds = []

getMyDetailsURL = 'https://webexapis.com/v1/people/me' 
userLookupUrl = 'https://webexapis.com/v1/people?email='
licenseLookupUrl = 'https://webexapis.com/v1/licenses'

# Functions
def checkAssignedLicense(wantedLicense, assignedLicense):
   for lic in wantedLicense:
        if lic in assignedLicense:
            return ('assigned')


def userLookup(email):
    response = requests.request("GET", userLookupUrl + email, headers=defaultHeaders)
    if response.status_code == 200:
        if response.json()['items']:
         for user in response.json()['items']:
            licenses = user['licenses']
            goodUser = checkAssignedLicense(callingLicenseIds, licenses)
            if goodUser == 'assigned':
               return(user['id'])
            else:
               print (f'ERROR: Skipping UserID {email} - Invalid user or does not have a Calling License.')
        else:
          print (f'ERROR: Skipping UserID {email} - Invalid user or does not have a Calling License.')
    else:
      print (f'ERROR: Something went wrong retriving Virtual Line {email} - Skipping')


#############   User Input and Validation  #############
print('This script requires two inputs:')
print('    1. An access token used to authorize the API calls\n       (You can get yours from https://developer.webex.com/docs/api/getting-started)\n')
print('    2. The full file path on your device for an input CSV file\n       (ex: C:\Scripts\huntAgents.csv on Windows or ~/Scripts/huntAgents.csv on Mac)\n')


# Loop to allow the user to input an access token until successful.
validationSuccess = 0
while (validationSuccess == 0):
    if not bearerToken :
        bearerToken = input('Please enter your access token:  ')
        defaultHeaders = {
                        'Authorization': 'Bearer ' + bearerToken 
                        }
    # Get People API Call to validate access token.
    validationResponse = requests.get(getMyDetailsURL, headers=defaultHeaders)
    if validationResponse.status_code == 401:
        # This means the access token was invalid.
        print('Access Token was invalid.  Please check your access token was entered correctly and hasn\'t expired and try again below.\n')
        bearerToken = ''
    else:
        validationSuccess = 1
print('Access Token validated succesfully.\n')


# Get CSV file and read it into
input_file = input('Enter CSV file name or full path: ')
with open(input_file, 'r', encoding='utf8') as my_file:
    csv_file = reader(my_file)
    next(my_file)
    for row in csv_file:
        userIDs.append(row[0])
#############   End User Input  #############


# Get list of all Webex Calling Licenses IDs
response = requests.request("GET", licenseLookupUrl, headers=defaultHeaders)
for entry in response.json()['items']:
  if entry['name'] == 'Webex Calling - Professional':
    callingLicenseIds.append(entry['id'])

# Lookup user ID and reset the PIN
for entry in userIDs:
  print(f'Processing {entry}')
  personId = userLookup(entry)
  if personId != None:

    headers = {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + bearerToken 
    }
    resetPinUrl = f'https://webexapis.com/v1/people/{personId}/features/voicemail/actions/resetPin/invoke'
    response = requests.request("POST", resetPinUrl, headers=headers)

    if response.status_code != 204:
        print('ERROR: ')
        print(response.status_code)
        print(response.text)
    else:
        print(f'INFO: {entry} PIN reset.')
