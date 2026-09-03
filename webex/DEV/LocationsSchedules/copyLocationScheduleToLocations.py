""" Python Script to Copy Location Schedule (holiday) to new locations in Control Hub
    
As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.

"""
__author__ = "Dan Fox"
__date__ = "2026/08/21"

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
locationsUrl = 'https://webexapis.com/v1/locations'
telephonyLocationURL = 'https://webexapis.com/v1/telephony/config/locations/'

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

def getLocationSchedules(locationID):
   response = requests.request("GET", telephonyLocationURL + locationID + '/schedules', headers=defaultHeaders)
   if response.status_code == 200:
    print(response.text.encode('utf8'))

   
#    url = "https://webexapis.com/v1/telephony/config/locations/405c859b-3875-49c2-a93c-d5c251b87a1a/schedules"

# payload = None

# headers = {
#     "Authorization": "Bearer NzQ0MzI3OWYtYjkwNC00ZTU0LWI1NjItZjBmMTUzMzYxMDJlNTFjNDkwOTEtMzRl_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd",
#     "Accept": "application/json"
# }

# response = requests.request('GET', url, headers=headers, data = payload)

# print(response.text.encode('utf8'))
   

def main():
    """
    Menu to choose single phone or list
    """

if __name__ == '__main__':
    """
    Authentication to Control Hub:
    """
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

   
    """
    Begin script work:
    """

    originLocation = 'Newman%20House'
    destinLocation = 'Foxden-CALL'

    originLocationID = getLocationID(originLocation)
    destinLocationID = getLocationID(destinLocation)

    getLocationSchedules(originLocationID)