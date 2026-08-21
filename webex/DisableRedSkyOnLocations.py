
import requests
import json

bearerToken = 'ZjM5ZGFjMGMtZTMwNC00MTJiLTkwOTUtZTQ0NjhhNWI0ZTljOGZhYWY0NGEtOGYw_PF84_384514e5-a1fb-40ab-b4f9-19a09687d6bd'

####. Get list of Location ID's:
url = "https://webexapis.com/v1/telephony/config/locations"

payload = None

headers = {
    "Authorization": "Bearer " + bearerToken,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

response = requests.request('GET', url, headers=headers, data = payload)

# print(response.text.encode('utf8'))

data = json.loads(response.text)

# print(f'INFO: This is the data output:')
# print(data)

# Build list of Location IDs
location_ids = [location["id"] for location in data["locations"]]

# Print each Location ID
print(f"Found {len(location_ids)} Location ID(s):\n")
for loc_id in location_ids:
    print(loc_id)
    try:
        url = "https://webexapis.com/v1/telephony/config/locations/" + loc_id + "/redSky/status"
        payload = '''{ "complianceStatus": "OPTED_OUT" }'''
        headers = {
        "Authorization": "Bearer " + bearerToken,
        "Content-Type": "application/json",
        "Accept": "application/json"
        }
        response = requests.request('PUT', url, headers=headers, data = payload)

        print(response.text.encode('utf8'))
    except:
        print(f'Failed for {loc_id}')

