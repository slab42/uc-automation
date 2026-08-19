import requests
import json
from csv import reader

# bearerToken = 'NzExYWJlZTEtMDU3ZC00ZTQ1LWFkMTktNjk1Y2Q2Mjk5NDM4MGQwYmYwNzktZWZk_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd'
bearerToken = ''
huntGroupId = ''
locationId = ''
menu = {}
emailsAndDns = []
callingLicenseIds = []
huntGroupList = []
agentsForHuntGroup = []
erroredUsers = []

getMyDetailsURL = 'https://webexapis.com/v1/people/me'
huntGroupUpdateUrl = f'https://webexapis.com/v1/telephony/config/locations/{locationId}/huntGroups/{huntGroupId}'
userLookupUrl = 'https://webexapis.com/v1/people?email='
licenseLookupUrl = 'https://webexapis.com/v1/licenses'
extensionLookupUrl = 'https://webexapis.com/v1/telephony/config/numbers?extension='
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


def extensionLookup(dn):
  response = requests.request("GET", extensionLookupUrl + dn, headers=defaultHeaders)
  if response.status_code == 200:
    if response.json()['phoneNumbers']:
      for line in response.json()['phoneNumbers']:
        return({'id' : line['owner']['id']})
    else:
      print (f'ERROR: Skipping Extension {dn} - Invalid DN.')
  else:
    print (f'ERROR: Something went wrong retriving Extension {dn} - Skipping')


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
        newId = extensionLookup(entry)
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


def delNoneOrBlank(payload):
  d = json.loads(payload)
  for key, value in list(d.items()):
    if value is None:
         del d[key]
    elif value == "":
         print(d[key])
         del d[key]
  return(json.dumps(d))

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
    for index, row in enumerate(csv_file, start=2):
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
                "waitingEnabled": "false",
                "noAnswer": {
                    "nextAgentEnabled": "true",
                    "nextAgentRings": "5",
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
            "agents": agentsForHuntGroup,
            "enabled": "true"
        })

        # Create Hunt Group
        headers = {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + bearerToken 
        }

        huntGroupCreateUrl = f'https://webexapis.com/v1/telephony/config/locations/{locationId}/huntGroups'
        response = requests.request("POST", huntGroupCreateUrl, headers=headers, data=payload, timeout=3)

      
        if response.status_code != 201:
            print(f'ERROR: Row {index}, Response Code: {response.status_code}\n {response.text}')
        else:
            print(f'INFO: Hunt Group Created Successfully: {name}.')

      else:
         print(f'ERROR: Incomplete data in row {index}.')
    
      #Clear the agents list after the loops
      agentsForHuntGroup = []
