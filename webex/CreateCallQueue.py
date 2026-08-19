import requests
import json
from csv import reader


bearerToken = ''
huntGroupId = ''
locationId = ''
emailsAndDns = []
callingLicenseIds = []
agentsForHuntGroup = []

getMyDetailsURL = 'https://webexapis.com/v1/people/me'
userLookupUrl = 'https://webexapis.com/v1/people?email='
licenseLookupUrl = 'https://webexapis.com/v1/licenses'
virtualLineLookupUrl = 'https://webexapis.com/v1/telephony/config/virtualLines?phoneNumber='
locationsUrl = 'https://webexapis.com/v1/locations'


# Functions
def checkAssignedLicense(wantedLicense, assignedLicense):
   for lic in wantedLicense:
        if lic in assignedLicense:
            return ('assigned')


def userLookup(email):
    response = requests.request("GET", userLookupUrl + email, headers=defaultHeaders, timeout=3)
    if response.status_code == 200:
        if response.json()['items']:
         for user in response.json()['items']:
            licenses = user['licenses']
            goodUser = checkAssignedLicense(callingLicenseIds, licenses)
            if goodUser == 'assigned':
               return({'id' : user['id']})
            else:
               print (f'ERROR: Skipping UserID {email} - Invalid user or does not have a Calling License.')
        else:
          print (f'ERROR: Skipping UserID {email} - Invalid user or does not have a Calling License.')
    else:
      print (f'ERROR: Something went wrong retriving Virtual Line {email} - Skipping')


def virtualLineLookup(dn):
  response = requests.request("GET", virtualLineLookupUrl + dn, headers=defaultHeaders, timeout=3)
  if response.status_code == 200:
    if response.json()['virtualLines']:
      for line in response.json()['virtualLines']:
        return({'id' : line['id']})
    else:
      print (f'ERROR: Skipping Virtual Line {dn} - Invalid DN.')
  else:
    print (f'ERROR: Something went wrong retriving Virtual Line {dn} - Skipping')


def getLocationID(name):
  response = requests.request("GET", locationsUrl + '?name=' + name, headers=defaultHeaders, timeout=3)
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


def addAgentId(entry):
  if entry:
    if entry.isnumeric():
        newId = virtualLineLookup(entry)
        if newId != None:
          agentsForHuntGroup.append(newId)
    else:
        newId = userLookup(entry)
        if newId is not None:
          agentsForHuntGroup.append(newId)


def callingLicenseIdLookup():
  response = requests.request("GET", licenseLookupUrl, headers=defaultHeaders, timeout=3)
  for entry in response.json()['items']:
    if entry['name'] == 'Webex Calling - Professional':
      callingLicenseIds.append(entry['id'])



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
    validationResponse = requests.get(getMyDetailsURL, headers=defaultHeaders, timeout=3)
    if validationResponse.status_code == 401:
        # This means the access token was invalid.
        print('Access Token was invalid.  Please check your access token was entered correctly and hasn\'t expired and try again below.\n')
        bearerToken = ''
    else:
        validationSuccess = 1
print('Access Token validated succesfully.\n')


# Get current list of Webex Calling License IDs
callingLicenseIdLookup()

# Read the CSV in and create the hunt group.
input_file = input('Enter CSV file name or full path: ')
with open(input_file, 'r', encoding='utf8') as my_file:
    csv_file = reader(my_file)
    next(my_file)
    for index, row in enumerate(csv_file, start=1):
    # for row in csv_file:
      name = checkForData(row[0])
      locationId = getLocationID(row[1])
      firstName = checkForData(row[3])
      lastName = checkForData(row[4])
      phoneNumber = checkForData(row[5])
      extension = checkForData(row[6])
      policy = checkForData(row[7])
      destination = checkForData(row[8])
      addAgentId(row[10])
      addAgentId(row[11])
      addAgentId(row[12])
      addAgentId(row[13])
      addAgentId(row[14])
      addAgentId(row[15])
      addAgentId(row[16])
      addAgentId(row[17])
      addAgentId(row[18])
      addAgentId(row[19])

      if name and locationId and policy and agentsForHuntGroup and destination:
        payload = json.dumps({
            "name": name,
            "phoneNumber": phoneNumber,
            "extension": extension,
            "firstName": firstName,
            "lastName": lastName,
            "callPolicies": {
                "policy": policy,
                "routingType": "SKILL_BASED",
                "waitingEnabled": "false",
                "noAnswer": {
                    "nextAgentEnabled": "true",
                    "nextAgentRings": "3",
                    "forwardEnabled": "true",
                    "numberOfRings": "15",
                    "destination" : destination,
                    "destinationVoicemailEnabled": "false"
                    },
                "businessContinuity": {
                    "enabled": "true",
                    "destination" : destination,
                    "destinationVoicemailEnabled": "false"
                    }
                },
            "queueSettings": {
                "queueSize": "10",
                "callOfferToneEnabled": "true",
                "resetCallStatisticsEnabled": "true",
                "overflow": {
                    "action": "PERFORM_BUSY_TREATMENT",
                    "overflowAfterWaitEnabled": "false",
                    "overflowAfterWaitTime": "30",
                    "playOverflowGreetingEnabled": "false",
                    "greeting": "DEFAULT",
                    "audioAnnouncementFiles": [
                {
                    "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                    "fileName": "announcement.wav",
                    "mediaFileType": "WAV",
                    "level": "LOCATION"
                }
            ]
                },
                "welcomeMessage": {
                    "enabled": "true",
                    "alwaysEnabled": "false",
                    "greeting": "DEFAULT",
                    "audioAnnouncementFiles": [
                {
                    "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                    "fileName": "announcement.wav",
                    "mediaFileType": "WAV",
                    "level": "LOCATION"
                }
            ]
                },
                "waitMessage": {
                    "enabled": "true",
                    "waitMode": "POSITION",
                    "handlingTime": "100",
                    "defaultHandlingTime": "100",
                    "queuePosition": "100",
                    "highVolumeMessageEnabled": "false",
                    "estimatedWaitingTime": "600",
                    "playUpdatedEstimatedWaitMessage": "true"
                },
                "comfortMessage": {
                    "enabled": "true",
                    "timeBetweenMessages": "10",
                    "greeting": "DEFAULT",
                    "audioAnnouncementFiles": [
                {
                    "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                    "fileName": "announcement.wav",
                    "mediaFileType": "WAV",
                    "level": "LOCATION"
                }
            ]
                },
                "mohMessage": {
                    "normalSource": {
                        "enabled": "true",
                        "greeting": "DEFAULT",
                        "audioAnnouncementFiles": [
                    {
                        "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                        "fileName": "announcement.wav",
                        "mediaFileType": "WAV",
                        "level": "LOCATION"
                    }
                ]
                    },
                    "alternateSource": {
                        "enabled": "true",
                        "greeting": "DEFAULT",
                        "audioAnnouncementFiles": [
                    {
                        "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                        "fileName": "announcement.wav",
                        "mediaFileType": "WAV",
                        "level": "LOCATION"
                    }
                ]
                    }
                },
                "comfortMessageBypass": {
                    "enabled": "true",
                    "callWaitingAgeThreshold": "30",
                    "greeting": "CUSTOM",
                    "audioAnnouncementFiles": [
                {
                    "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                    "fileName": "announcement.wav",
                    "mediaFileType": "WAV",
                    "level": "LOCATION"
                }
            ]
                },
                "whisperMessage": {
                    "enabled": "true",
                    "greeting": "DEFAULT",
                    "audioAnnouncementFiles": [
                {
                    "id": "Y2lzY29zcGFyazovL3VzL0FOTk9VTkNFTUVOVC9jZWRkODcwYS1lMTkzLTQxNmQtYmM3OS1mNzkyYmUyMzlhOGI",
                    "fileName": "announcement.wav",
                    "mediaFileType": "WAV",
                    "level": "LOCATION"
                }
            ]
                }
            } ,
            "agents": agentsForHuntGroup,
            "enabled": "true",
            "phoneNumberForOutgoingCallsEnabled": "true",
            "allowAgentJoinEnabled": "true"
        })
        # Create Hunt Group
        headers = {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + bearerToken 
        }

        callQueueCreateUrl = f'https://webexapis.com/v1/telephony/config/locations/{locationId}/queues'
        response = requests.request("POST", callQueueCreateUrl, headers=headers, data=payload, timeout=3)

      
        if response.status_code != 201:
            print(f'ERROR: Row {index}, Response Code: {response.status_code}\n {response.text}')
        else:
            print(f'INFO: Hunt Group Created Successfully: {name}.')

      else:
         print(f'ERROR: Incomplete data in row {index}.')
    
      #Clear the agents list after the loops
      agentsForHuntGroup = []
