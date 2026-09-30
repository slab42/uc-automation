# TITLE: Validate Phone Compatibility
""" Python Script to validate physical phone compatibility for Webex Calling

This script reads a CSV of phone models and MAC addresses and validates each
entry against the organization's supported device list AND against Webex
itself, so issues like an unsupported hardware/model, a malformed MAC, or a
MAC already registered to another device in the org are caught before
onboarding is attempted. Checks performed:

1) The phone model is a Webex Calling supported device for this org
   (GET /v1/telephony/config/supportedDevices, matched against both the
   API 'model' code and 'displayName').
2) The device's onboarding methods include MAC address activation
   (some supported devices only support activation code onboarding).
3) The MAC address is valid and not already in use in Webex, per Webex's
   own bulk validation endpoint
   (POST /v1/telephony/config/devices/actions/validateMacs/invoke), which
   returns one of: AVAILABLE, UNAVAILABLE (already in use), DUPLICATE_IN_LIST,
   or INVALID for each submitted MAC.

Requires a full or device administrator access token with scope
spark-admin:telephony_config_write (the validateMacs endpoint is a write-scoped
API even though it only validates).

CSV format (field order matters, header row is skipped):

model,mac
Cisco 8865,6C74AAAAAAAA
Cisco 8845,AC7A594BBBBB

Results are printed to the console and written to a CSV report in
_DATA/reports/<timestamp>-phone_compatibility_results.csv.

As always, the cloud is a constant change validate any issues against Cisco Developer API documentation.
Based on:
https://developer.webex.com/calling/docs/api/v1/device-call-settings/list-supported-devices
https://developer.webex.com/docs/api/v1/device-call-settings/validate-a-list-of-mac-address
"""
__author__ = "Dan Fox"
__date__ = "2026/09/30"

import warnings
warnings.simplefilter('ignore')

#############  Imports  #############
import requests
import re
import time
import sys
from csv import reader, writer
from pathlib import Path
#used for settings.ini file:
import configparser
import os


#############  Definitions  #############

bearerToken = ''
getMyDetailsURL = 'https://webexapis.com/v1/people/me'
supportedDevicesUrl = 'https://webexapis.com/v1/telephony/config/supportedDevices'
validateMacsUrl = 'https://webexapis.com/v1/telephony/config/devices/actions/validateMacs/invoke'

MAC_PATTERN = re.compile(r'^[0-9A-Fa-f]{12}$')

# Webex only documents MAC list validation in small examples; batch requests
# to stay well under any undocumented request size limit.
MAC_VALIDATION_BATCH_SIZE = 50

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


def normalizeMac(mac):
    """Strip separators and any non-hex characters, then uppercase the result."""
    return re.sub(r'[^0-9A-Fa-f]', '', mac).upper()


def getSupportedDevices():
    """Retrieve the org's supported device list, keyed by lowercased model and displayName."""
    devices = {}
    response = requests.request("GET", supportedDevicesUrl, headers=defaultHeaders, timeout=10)
    if response.status_code == 200:
        for device in response.json().get('devices', []):
            entry = {
                'model': device.get('model', ''),
                'displayName': device.get('displayName', ''),
                'onboardingMethod': device.get('onboardingMethod', []),
            }
            for key in (device.get('model'), device.get('displayName')):
                if key:
                    devices[key.strip().lower()] = entry
    else:
        print(f'ERROR: Unable to retrieve supported devices list.\n Response Code: {response.status_code}\n {response.text}')
    return(devices)


def validateMacsWithWebex(macs):
    """Validate a list of normalized MACs against Webex itself.

    Returns a dict keyed by normalized MAC -> {'state': ..., 'message': ...}.
    State is one of AVAILABLE, UNAVAILABLE (already in use), DUPLICATE_IN_LIST,
    or INVALID, as returned by Webex.
    """
    macStates = {}
    for start in range(0, len(macs), MAC_VALIDATION_BATCH_SIZE):
        batch = macs[start:start + MAC_VALIDATION_BATCH_SIZE]
        payload = {'macs': batch}
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + bearerToken}
        dprint(f'Validating MAC batch: {batch}')
        response = requests.post(validateMacsUrl, headers=headers, json=payload, timeout=15)
        dprint(f'Raw validateMacs response ({response.status_code}): {response.text}')
        if response.status_code == 200:
            body = response.json()

            # Webex only returns "status": "OK" with no macStatus array when every
            # MAC in the batch is fine. macStatus is only populated (and may only
            # list the offending MACs) when "status": "ERRORS". Default the whole
            # batch to AVAILABLE, then overlay any entries Webex actually returned.
            for mac in batch:
                macStates[mac] = {'state': 'AVAILABLE', 'message': ''}

            for entry in body.get('macStatus', []):
                mac = normalizeMac(entry.get('mac', ''))
                macStates[mac] = {
                    'state': entry.get('state', 'INVALID'),
                    'message': entry.get('message', ''),
                }
        else:
            print(f'ERROR: MAC validation call failed for batch starting at row offset {start}.\n Response Code: {response.status_code}\n {response.text}')
            for mac in batch:
                macStates[mac] = {'state': 'UNKNOWN', 'message': 'Webex validateMacs call failed'}
    return(macStates)


def validateRow(model, mac, supportedDevices, macStates):
    """Return (status, reason) for a single CSV row."""
    if not model or not mac:
        return('INVALID', 'Missing model or MAC address')

    normalizedMac = normalizeMac(mac)
    if not MAC_PATTERN.match(normalizedMac):
        return('INVALID', f'MAC address "{mac}" is not a valid 12 hex-digit MAC')

    device = supportedDevices.get(model.strip().lower())
    if not device:
        return('INVALID', f'Model "{model}" is not a supported Webex Calling device for this org')

    macResult = macStates.get(normalizedMac, {'state': 'UNKNOWN', 'message': ''})
    macState = macResult['state']
    macMessage = macResult['message']

    if macState == 'UNAVAILABLE':
        return('INVALID', f'MAC address "{normalizedMac}" is already in use in Webex ({macMessage or "no further detail"})')
    if macState == 'DUPLICATE_IN_LIST':
        return('INVALID', f'MAC address "{normalizedMac}" is duplicated elsewhere in the CSV')
    if macState == 'INVALID':
        return('INVALID', f'Webex rejected MAC address "{normalizedMac}" as invalid ({macMessage or "no further detail"})')
    if macState == 'UNKNOWN':
        return('WARNING', f'MAC address "{normalizedMac}" could not be validated against Webex (call failed)')

    if device['onboardingMethod'] and 'MAC_ADDRESS' not in device['onboardingMethod']:
        return('WARNING', f'Model "{model}" does not support MAC address onboarding (supports: {", ".join(device["onboardingMethod"])})')

    return('VALID', f'Model "{model}" is supported ({device["displayName"]}) and MAC "{normalizedMac}" is available in Webex')


# Begin Script
print('This script requires two inputs:')
print('    1. An access token used to authorize the API calls\n       (You can get yours from https://developer.webex.com/docs/api/getting-started)\n')
print('    2. The full file path on your device for an input CSV file\n       (ex: C:\\Scripts\\phones.csv on Windows or ~/Scripts/phones.csv on Mac)\n')

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


### Retrieve org supported device list:
supportedDevices = getSupportedDevices()
if not supportedDevices:
    print('ERROR: No supported devices retrieved, cannot validate compatibility. Ending script.')
    sys.exit(1)
print(f'INFO: Retrieved {len(supportedDevices)} supported device name/model entries for this org.\n')


### Read the CSV in.
input_file = input('Enter CSV file name or full path: ')

start_time = time.time()

rows = []
with open(input_file, 'r', encoding='utf-8-sig', errors='replace') as my_file:
    csv_file = reader(my_file)
    try:
        first_row = next(csv_file)
        dprint(f'Headers are: {first_row}')
    except StopIteration:
        print('ERROR: Input CSV file is empty. Ending script.')
        sys.exit(1)

    for index, row in enumerate(csv_file, start=2):
        model = checkForData(row[0]) if len(row) > 0 else ''
        mac = checkForData(row[1]) if len(row) > 1 else ''
        rows.append({'row': index, 'model': model, 'mac': mac})

### Validate all MAC addresses against Webex in batches before evaluating rows:
candidateMacs = [normalizeMac(r['mac']) for r in rows if r['mac'] and MAC_PATTERN.match(normalizeMac(r['mac']))]
print(f'INFO: Validating {len(candidateMacs)} MAC address(es) against Webex.\n')
macStates = validateMacsWithWebex(candidateMacs) if candidateMacs else {}

results = []
for entry in rows:
    index, model, mac = entry['row'], entry['model'], entry['mac']
    status, reason = validateRow(model, mac, supportedDevices, macStates)
    results.append({'row': index, 'model': model, 'mac': mac, 'status': status, 'reason': reason})

    if status == 'VALID':
        print(f'INFO: Row {index} - {reason}')
    elif status == 'WARNING':
        print(f'WARNING: Row {index} - {reason}')
    else:
        print(f'ERROR: Row {index} - {reason}')


### Write results report:
basepath = Path(__file__).resolve().parent
reports_dir = basepath.parent / '_DATA' / 'reports'
reports_dir.mkdir(parents=True, exist_ok=True)

timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
output_file = reports_dir / f'{timestamp}-phone_compatibility_results.csv'

with open(output_file, 'w', newline='', encoding='utf-8') as out_file:
    csv_writer = writer(out_file)
    csv_writer.writerow(['row', 'model', 'mac', 'status', 'reason'])
    for result in results:
        csv_writer.writerow([result['row'], result['model'], result['mac'], result['status'], result['reason']])

print(f'\nINFO: Results written to: {output_file}')


### End script:
validCount = sum(1 for r in results if r['status'] == 'VALID')
warningCount = sum(1 for r in results if r['status'] == 'WARNING')
invalidCount = sum(1 for r in results if r['status'] == 'INVALID')
print(f'INFO: Summary - Valid: {validCount}, Warnings: {warningCount}, Invalid: {invalidCount}, Total: {len(results)}')

end_time = time.time()
execution_time = end_time - start_time
print(f"INFO: Execution time: {execution_time:.4f} seconds.")
