import requests
import json
from csv import reader

# bearerToken = 'MjZiZmUxZWUtMzAyYy00MWY5LWFmYjYtOTg0MGQyMDVlYmI0NWE4YWYwNjMtOTFh_PF84_64492b1f-f6e5-4acd-b532-9a0e5091fa44'
bearerToken = ''
groupId = ''
locationId = ''
menu = {}
emails = []
callingLicenseIds = []
groupList = []
usersForGroup = []
erroredUsers = []

getMyDetailsURL = 'https://webexapis.com/v1/people/me' 
groupListUrl = 'https://webexapis.com/v1/groups'
groupUpdateUrl = f'https://webexapis.com/v1/groups/{groupId}'
userLookupUrl = 'https://webexapis.com/v1/people?email='


# Functions
def userLookup(email):
    response = requests.request("GET", userLookupUrl + email, headers=defaultHeaders)
    if response.status_code == 200:
        if response.json()['items']:
         for user in response.json()['items']:
            return({'id' : user['id']})       
        else:
          print (f'ERROR: Skipping UserID {email} - Invalid user ID.')
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
        emails.append(row[0])
#############   End User Input  #############


# Get List of Groups and check to make sure it is not 0.
response = requests.request("GET", groupListUrl, headers=defaultHeaders)
if response.status_code != 200 or len(response.json()['groups']) == 0:
    print(response.status_code)
    print(response.text)
    quit()

# Break Json into readable list for menu
for groups in response.json()['groups']:
    groupList.append(groups)

# Create a menu of Hunt Groups to Choose From
print()
print('Choose a Hunt Group')
print('------------------')
for index, item in enumerate(groupList, start=1):
    menu[str(index)] = item.get('displayName')
for index, menuItem in menu.items():
    print(f'{index}. {menuItem}')
while True:
    choice = input('Please make a selection: ')
    if choice in menu.keys():
        groupSelected = menu[choice]
        break
    else:
        print('ERROR: please select a valid choice.')

# Get the IDs of the selected Group and Location
for groups in groupList:
    if groups['displayName'] == groupSelected:
       print('INFO: ' + groups['displayName'] + ' has been selected.')
       groupId = groups['id']
       break

# Get a list of IDs for Hunt Group
for entry in emails:
  print(f'Processing {entry}...')
  newId = userLookup(entry)
  if newId is not None:
     usersForGroup.append(newId)

# print(usersForGroup)

# Update Group
payload = json.dumps({
  "members" : usersForGroup
})

headers = {
  'Content-Type': 'application/json',
  'Authorization': 'Bearer ' + bearerToken 
}

groupUpdateUrl = f'https://webexapis.com/v1/groups/{groupId}'
response = requests.request("PATCH", groupUpdateUrl, headers=headers, data=payload)

if response.status_code not in [200, 201, 202]:
    print('ERROR: ')
    print(response.status_code)
    print(response.text)
else:
    print('INFO: Group Updated.')
