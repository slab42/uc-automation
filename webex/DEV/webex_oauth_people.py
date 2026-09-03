import requests
from urllib.parse import urlencode
import webbrowser
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

# OAuth Configuration
CLIENT_ID = "C028fab5afe7f30c79489de2dbc68d268ddfc3e70feea827d1ec84a07c79445ae"
CLIENT_SECRET = "ce38d84491bfd5dfecb71937f78cbd69abda1a01a0347630e9cb0fbfb6faf0a3"
REDIRECT_URI = "http://localhost:8000/callback"
AUTHORIZATION_URL = "https://webexapis.com/v1/authorize"
TOKEN_URL = "https://webexapis.com/v1/access_token"
PEOPLE_API_URL = "https://webexapis.com/v1/people"
SCOPE = "spark:people_read"

# Global variable to store auth code
auth_code = None
server = None

class CallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback from Webex"""
    def do_GET(self):
        global auth_code
        
        # Parse the authorization code from callback
        if "code=" in self.path:
            auth_code = self.path.split("code=")[1].split("&")[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization successful!</h1><p>You can close this window.</p></body></html>")
            print(f"Authorization code received: {auth_code}")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No authorization code received")
    
    def log_message(self, format, *args):
        """Suppress log messages"""
        pass

def get_authorization_code():
    """Step 1: Direct user to authorization URL"""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": "security_token"
    }
    
    auth_url = f"{AUTHORIZATION_URL}?{urlencode(params)}"
    print(f"Opening browser for authorization...")
    print(f"Authorization URL: {auth_url}\n")
    
    # Open browser for user to authorize
    webbrowser.open(auth_url)
    
    # Start local callback server
    global server
    server = HTTPServer(("localhost", 8000), CallbackHandler)
    print("Waiting for authorization callback on http://localhost:8000/callback...")
    
    # Handle one request
    server.handle_request()

def get_access_token(code):
    """Step 2: Exchange authorization code for access token"""
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    
    response = requests.post(TOKEN_URL, data=payload)
    
    if response.status_code == 200:
        token_data = response.json()
        return token_data.get("access_token")
    else:
        print(f"Error getting access token: {response.text}")
        return None

def get_people(access_token):
    """Step 3: Use access token to get list of people"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    response = requests.get(PEOPLE_API_URL, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error getting people: {response.text}")
        return None

def main():
    print("=" * 60)
    print("Webex OAuth API - Get People List")
    print("=" * 60)
    print()
    
    # Check if credentials are set
    if CLIENT_ID == "YOUR_CLIENT_ID" or CLIENT_SECRET == "YOUR_CLIENT_SECRET":
        print("ERROR: Please set CLIENT_ID and CLIENT_SECRET in the script")
        print("Visit https://developer.webex.com to register your app")
        return
    
    # Step 1: Get authorization code
    try:
        get_authorization_code()
    except KeyboardInterrupt:
        print("\nAuthorization cancelled")
        return
    
    global auth_code
    if not auth_code:
        print("Failed to get authorization code")
        return
    
    # Step 2: Exchange code for access token
    print("\nExchanging authorization code for access token...")
    access_token = get_access_token(auth_code)
    
    if not access_token:
        print("Failed to get access token")
        return
    
    print(f"Access token obtained successfully")
    
    # Step 3: Get people list
    print("\nFetching people list from Webex API...")
    people_data = get_people(access_token)
    
    if people_data:
        print("\nResponse:")
        print(json.dumps(people_data, indent=2))
    else:
        print("Failed to fetch people list")

if __name__ == "__main__":
    main()
