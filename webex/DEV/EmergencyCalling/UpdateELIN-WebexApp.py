""" Python Script to enable Webex App Emergency Calling (ELIN) for all calling-enabled users.

Finds every calling-enabled user in the org whose Webex App ELIN
(elinForWebexAppEnabled) is disabled, and updates them to enable it while
keeping their existing emergency callback selection unchanged.

No CSV input required - the user list comes from GET /v1/people?callingData=true.

This script defaults to a dry-run: it always assesses and reports the users
that need updating first, and will only apply changes after you type APPLY at
the confirmation prompt.

As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on: https://developer.webex.com/calling/docs/api/v1/emergency-callback-number/get-a-persons-emergency-callback-number
          https://developer.webex.com/calling/docs/api/v1/emergency-callback-number/update-a-persons-emergency-callback-number

"""
__author__ = "Dan Fox"
__date__ = "2026/09/02"

#############  Imports  #############

import requests
import json
import csv
import time
import re
import configparser
import os
import datetime

#############  Definitions  #############

bearerToken = ''
defaultHeaders = None
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
peopleURL = 'https://webexapis.com/v1/people'
emergencyCallbackURL = 'https://webexapis.com/v1/telephony/config/people/{personId}/emergencyCallbackNumber'

# Set to True to enable debug messages
DEBUG_MODE = False

def dprint(*args, **kwargs):
    if DEBUG_MODE:
        print("[DEBUG]", *args, **kwargs)

### Log files, written to a logs/ folder next to this script:
scriptDir = os.path.dirname(os.path.abspath(__file__))
logsDir = os.path.join(scriptDir, 'logs')
os.makedirs(logsDir, exist_ok=True)

### Log retention: keep at most 1 month of logs, and at most 120 files total.
logFileNamePattern = re.compile(r'ELIN_(?:report|failed)_(\d{8}-\d{4})\.csv$')
maxLogAgeDays = 30
maxLogFileCount = 120

def cleanupOldLogs():
    cutoff = datetime.datetime.now() - datetime.timedelta(days=maxLogAgeDays)

    logFiles = []
    for name in os.listdir(logsDir):
        match = logFileNamePattern.match(name)
        if not match:
            continue
        try:
            fileDate = datetime.datetime.strptime(match.group(1), '%Y%m%d-%H%M')
        except ValueError:
            continue
        logFiles.append((fileDate, os.path.join(logsDir, name)))

    remaining = []
    for fileDate, path in logFiles:
        if fileDate < cutoff:
            try:
                os.remove(path)
                dprint(f'Removed log file older than {maxLogAgeDays} days: {path}')
            except:
                print(f'[ERROR] Failed to remove old log file: {path}')
        else:
            remaining.append((fileDate, path))

    if len(remaining) > maxLogFileCount:
        remaining.sort(key=lambda entry: entry[0])
        for fileDate, path in remaining[:len(remaining) - maxLogFileCount]:
            try:
                os.remove(path)
                dprint(f'Removed excess log file (over {maxLogFileCount} limit): {path}')
            except:
                print(f'[ERROR] Failed to remove excess log file: {path}')

cleanupOldLogs()

fileTimestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
reportFile = os.path.join(logsDir, f'ELIN_report_{fileTimestamp}.csv')
failedFile = os.path.join(logsDir, f'ELIN_failed_{fileTimestamp}.csv')

reportHeaders = ['personId', 'email', 'selected', 'locationMemberId', 'elinEnabled', 'elinForWebexAppEnabled']
failedHeaders = ['personId', 'email', 'stage', 'errorDetail']

#############  Functions  #############

def logReportEntry(personId, email, selected, locationMemberId, elinEnabled, elinForWebexAppEnabled):
    try:
        with open(reportFile, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            if file.tell() == 0:
                writer.writerow(reportHeaders)
            writer.writerow([personId, email, selected, locationMemberId, elinEnabled, elinForWebexAppEnabled])
    except:
        print(f'[ERROR] Writing entry into report file FAILED.')

def logFailureEntry(personId, email, stage, errorDetail):
    try:
        with open(failedFile, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            if file.tell() == 0:
                writer.writerow(failedHeaders)
            writer.writerow([personId, email, stage, errorDetail])
    except:
        print(f'[ERROR] Writing entry into failed file FAILED.')

### Basic 429 handling - one retry honoring Retry-After:
def requestWithRetry(method, url, headers, data=None):
    response = requests.request(method, url, headers=headers, data=data, timeout=10)
    if response.status_code == 429:
        retryAfter = int(response.headers.get('Retry-After', 5))
        dprint(f'429 received, retrying after {retryAfter} seconds.')
        time.sleep(retryAfter)
        response = requests.request(method, url, headers=headers, data=data, timeout=10)
    return response

### Page through GET /v1/people?callingData=true, following the Link header:
def getAllCallingPeople():
    people = []
    url = peopleURL + '?callingData=true&max=1000'
    while url:
        response = requestWithRetry('GET', url, defaultHeaders)
        if response.status_code != 200:
            print(f'[ERROR] Failed to list people. Response Code: {response.status_code}\n {response.text}')
            break
        for person in response.json().get('items', []):
            people.append({
                'personId': person.get('id'),
                'email': (person.get('emails') or [''])[0]
            })
        url = response.links.get('next', {}).get('url')
    return people

### GET a person's emergency callback number settings:
def getEmergencyCallbackNumber(personId):
    url = emergencyCallbackURL.format(personId=personId)
    response = requestWithRetry('GET', url, defaultHeaders)
    print(response)
    return response

### PUT a person's emergency callback number settings:
def updateEmergencyCallbackNumber(personId, selected, locationMemberId=None):
    body = {
        "selected": selected,
        "elinEnabled": True,
        "elinForWebexAppEnabled": True
    }
    if locationMemberId is not None:
        body["locationMemberId"] = locationMemberId
    payload = json.dumps(body)
    dprint(f'payload is: {payload}')

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + bearerToken
    }
    response = requestWithRetry('PUT', url=emergencyCallbackURL.format(personId=personId), headers=headers, data=payload)
    return response


############ Begin Script #######################
def main():
    global bearerToken, defaultHeaders

    print('This script requires an access token used to authorize the API calls.')
    print('(You can get yours from https://developer.webex.com/docs/api/getting-started)\n')

    # Check for settings.ini file and setting token:
    if not bearerToken:
        if os.path.isfile("settings.ini"):
            dprint("settings.ini file exists")
            config = configparser.ConfigParser()
            config.read('settings.ini')
            try:
                bearerToken = config['access']['bearerToken']
            except:
                dprint("Issue with accessing the settings.ini - bearerToken.")
                bearerToken = ''
            dprint(f'BearerToken is: {bearerToken}')
        else:
            print("No settings.ini file found, moving on.")

    # Loop to allow the user to input an access token until successful.
    validationSuccess = 0
    while (validationSuccess == 0):

        ### Request bearerToken if not present:
        if not bearerToken:
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

    ### Discover: list every calling-enabled person in the org.
    print('INFO: Discovering calling-enabled users...')
    people = getAllCallingPeople()
    print(f'INFO: Discovered {len(people)} calling-enabled users.\n')

    ### Assess: GET each person's emergency callback number settings.
    print('INFO: Assessing emergency calling (ELIN) settings for each user...')
    needsUpdate = []
    assessedCount = 0
    getFailedCount = 0

    for person in people:
        personId = person['personId']
        email = person['email']

        response = getEmergencyCallbackNumber(personId)
        if response.status_code != 200:
            print(f'[ERROR] {email}: Failed to get emergency callback number. Response Code: {response.status_code}')
            logFailureEntry(personId, email, 'GET emergencyCallbackNumber', f'{response.status_code}: {response.text}')
            getFailedCount += 1
            continue

        data = response.json()
        selected = data.get('selected')
        locationMemberId = data.get('locationMemberId')
        elinEnabled = data.get('elinEnabled')
        elinForWebexAppEnabled = data.get('elinForWebexAppEnabled')

        # locationMemberId is only present/required when selected == 'LOCATION_MEMBER_NUMBER'.
        if selected is None or elinForWebexAppEnabled is None:
            print(f'[ERROR] {email}: Response missing expected emergency calling fields.')
            logFailureEntry(personId, email, 'GET emergencyCallbackNumber', f'Missing expected fields in response: {data}')
            getFailedCount += 1
            continue

        assessedCount += 1

        if elinForWebexAppEnabled is False:
            dprint(f'{email}: elinForWebexAppEnabled is False, needs update.')
            needsUpdate.append({
                'personId': personId,
                'email': email,
                'selected': selected,
                'locationMemberId': locationMemberId,
                'elinEnabled': elinEnabled,
                'elinForWebexAppEnabled': elinForWebexAppEnabled
            })
            logReportEntry(personId, email, selected, locationMemberId, elinEnabled, elinForWebexAppEnabled)

    print(f'\nINFO: Assessment complete.')
    print(f'INFO: Discovered: {len(people)}, Assessed: {assessedCount}, Get failures: {getFailedCount}, Needing update: {len(needsUpdate)}')
    if needsUpdate:
        print(f'INFO: Dry-run report written to: {reportFile}')

    if not needsUpdate:
        print('\nINFO: No users need updates. Exiting.')
        return

    ### Confirm gate: dry run by default, only apply on explicit confirmation.
    print(f'\nThe following {len(needsUpdate)} users have elinForWebexAppEnabled = False:')
    for user in needsUpdate:
        print(f"  {user['email']} ({user['personId']})")

    confirm = input(f'\nPress Enter to update the {len(needsUpdate)} users listed above, or type exit to cancel (dry run only): ')
    if confirm.strip().lower() == 'exit':
        print('Exiting without making changes (dry run only).')
        return

    ### Apply: PUT the update for each user needing it.
    print('\nINFO: Applying updates...')
    appliedCount = 0
    putFailedCount = 0

    for user in needsUpdate:
        response = updateEmergencyCallbackNumber(user['personId'], user['selected'], user['locationMemberId'])
        if response.status_code in (200, 204):
            print(f"INFO: {user['email']} updated successfully.")
            appliedCount += 1
        else:
            print(f"[ERROR] {user['email']}: Update FAILED. Response Code: {response.status_code}")
            logFailureEntry(user['personId'], user['email'], 'PUT emergencyCallbackNumber', f'{response.status_code}: {response.text}')
            putFailedCount += 1

    ### End script: summary.
    print(f'\nINFO: Applied: {appliedCount}, Failed: {putFailedCount}')
    if getFailedCount or putFailedCount:
        print(f'INFO: Failure details written to: {failedFile}')


if __name__ == "__main__":
    main()
