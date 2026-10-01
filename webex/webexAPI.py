#!/usr/bin/env python3
"""
Webex REST API wrapper.

Counterpart of cucm/ucmAPI.py and cuc/cucAPI.py for Webex. Wraps a
requests.Session against https://webexapis.com with a bearer token, JSON
responses, retries and Link-header pagination.

Every public method returns the same dict shape as ucmAPI.AXL and cucAPI.CUC:
    {'success': bool, 'response': <payload>, 'error': str}

The wrapper never logs and never prints; callers log the results. The token
is held only on the session's Authorization header and never appears in a
return value or in an exception message produced here.

Two different API families both talk about "locations" and they are not
interchangeable (see CLAUDE.md): list_locations() uses
GET /v1/telephony/config/locations (scope spark-admin:telephony_config_read),
which is what this repo's integration is granted. GET /v1/locations
(spark-admin:locations_read) is a separate family and is not used here.

Usage from a script in this folder (cwd is webex/ when run via main.py):
    from webexAPI import Webex
    wx = Webex(token)
    result = wx.list_locations()
    if result['success']:
        for location in result['response']:
            print(location['name'])
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = 'https://webexapis.com/v1'
DEFAULT_TIMEOUT = 60
DEFAULT_PAGE_SIZE = 500
MAX_PAGES = 200


def _result(success, response=None, error=''):
    """Build the standard result dict."""
    return {'success': success, 'response': response if response is not None else '', 'error': error}


def _error_text(resp):
    """Readable message from a Webex error body, falling back to the status line."""
    try:
        body = resp.json()
    except ValueError:
        return f'HTTP {resp.status_code}: {(resp.text or "").strip()[:300]}'
    message = body.get('message') or body.get('errors') or body
    tracking = body.get('trackingId')
    text = f'HTTP {resp.status_code}: {message}'
    return f'{text} (trackingId {tracking})' if tracking else text


class Webex:
    """Thin client for the Webex public APIs."""

    def __init__(self, token, timeout=DEFAULT_TIMEOUT, page_size=DEFAULT_PAGE_SIZE):
        """
        Args:
            token (str): Webex admin access token (never stored anywhere but the session header)
            timeout (int): per-request timeout in seconds
            page_size (int): `max` used for paged list calls
        """
        self.timeout = timeout
        self.page_size = page_size
        self.base_url = BASE_URL

        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })
        retry = Retry(
            total=4, connect=4, read=4, backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(['GET', 'DELETE']),
            respect_retry_after_header=True,
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    # ------------------------------------------------------------------ low level

    def _url(self, path):
        """Accept '/people', 'people' or a full https URL."""
        if path.startswith('http'):
            return path
        return f'{self.base_url}/{path.lstrip("/")}'

    def get(self, path, params=None):
        """GET one resource or one page. Returns the decoded JSON body."""
        try:
            resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        except requests.RequestException as e:
            return _result(False, error=f'Request failed: {e}')
        if resp.status_code >= 400:
            return _result(False, error=_error_text(resp))
        try:
            return _result(True, resp.json() if resp.content else {})
        except ValueError as e:
            return _result(False, error=f'Invalid JSON in response: {e}')

    def post(self, path, payload):
        """POST a JSON body. Returns the decoded JSON body (or {} on 204)."""
        try:
            resp = self.session.post(self._url(path), json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            return _result(False, error=f'Request failed: {e}')
        if resp.status_code >= 400:
            return _result(False, error=_error_text(resp))
        try:
            return _result(True, resp.json() if resp.content else {})
        except ValueError:
            return _result(True, {})

    def put(self, path, payload):
        """PUT a JSON body. Returns the decoded JSON body (or {} on 204)."""
        try:
            resp = self.session.put(self._url(path), json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            return _result(False, error=f'Request failed: {e}')
        if resp.status_code >= 400:
            return _result(False, error=_error_text(resp))
        try:
            return _result(True, resp.json() if resp.content else {})
        except ValueError:
            return _result(True, {})

    def patch(self, path, payload):
        """PATCH a JSON body. Returns the decoded JSON body (or {} on 204)."""
        try:
            resp = self.session.patch(self._url(path), json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            return _result(False, error=f'Request failed: {e}')
        if resp.status_code >= 400:
            return _result(False, error=_error_text(resp))
        try:
            return _result(True, resp.json() if resp.content else {})
        except ValueError:
            return _result(True, {})

    def delete(self, path):
        """DELETE one resource. Success is any 2xx."""
        try:
            resp = self.session.delete(self._url(path), timeout=self.timeout)
        except requests.RequestException as e:
            return _result(False, error=f'Request failed: {e}')
        if resp.status_code >= 400:
            return _result(False, error=_error_text(resp))
        return _result(True, {})

    def get_paged(self, path, key, params=None):
        """Follow Link: rel="next" and concatenate body[key] from every page.

        Webex paginates with an absolute `next` URL in the Link header, so the
        follow-up requests must not re-send the original query string.
        """
        params = dict(params or {})
        params.setdefault('max', self.page_size)
        items = []
        url = self._url(path)
        for _page in range(MAX_PAGES):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                return _result(False, error=f'Request failed: {e}')
            if resp.status_code >= 400:
                return _result(False, error=_error_text(resp))
            try:
                body = resp.json() if resp.content else {}
            except ValueError as e:
                return _result(False, error=f'Invalid JSON in response: {e}')
            items.extend(body.get(key, []) or [])
            url = resp.links.get('next', {}).get('url')
            if not url:
                return _result(True, items)
            params = None
        return _result(True, items)

    # ------------------------------------------------------------------ identity

    def me(self):
        """GET /people/me - validates the token and reveals the org id."""
        return self.get('/people/me')

    # ------------------------------------------------------------------ locations

    def list_locations(self):
        """Calling locations (GET /telephony/config/locations)."""
        return self.get_paged('/telephony/config/locations', 'locations')

    def get_location(self, location_id):
        """One calling location with its full configuration."""
        return self.get(f'/telephony/config/locations/{location_id}')

    def get_redsky_status(self, location_id):
        """RedSky (emergency calling) compliance status for one location."""
        return self.get(f'/telephony/config/locations/{location_id}/redSky/status')

    def set_redsky_status(self, location_id, opted_out=True):
        """Turn RedSky routing on or off for one location.

        Based on DisableRedSkyOnLocations.py, which always opts out.
        """
        status = 'OPTED_OUT' if opted_out else 'OPTED_IN'
        return self.put(f'/telephony/config/locations/{location_id}/redSky/status',
                        {'complianceStatus': status})

    # ------------------------------------------------------------------ people

    def list_people(self, params=None):
        """People in the org (GET /people). Webex requires a filter for large orgs."""
        return self.get_paged('/people', 'items', params=params)

    def get_person(self, person_id):
        return self.get(f'/people/{person_id}')

    def delete_person(self, person_id):
        return self.delete(f'/people/{person_id}')

    def reset_person_pin(self, person_id, pin):
        """Set a person's voicemail PIN (PUT /people/{id}/features/voicemail/actions/resetPin)."""
        return self.post(f'/telephony/config/people/{person_id}/actions/resetVoicemailPin/invoke',
                         {'pin': pin})

    # ------------------------------------------------------------------ workspaces and devices

    def list_workspaces(self, params=None):
        return self.get_paged('/workspaces', 'items', params=params)

    def get_workspace(self, workspace_id):
        return self.get(f'/workspaces/{workspace_id}')

    def create_workspace(self, payload):
        """Create a workspace (POST /workspaces). Based on CreateWorkspace.py."""
        return self.post('/workspaces', payload)

    def delete_workspace(self, workspace_id):
        return self.delete(f'/workspaces/{workspace_id}')

    def list_workspace_locations(self, params=None):
        """Workspace Locations (GET /workspaceLocations).

        This is a third, distinct API family from both the Calling Locations
        used by list_locations() and the core /v1/locations family this
        integration does not have scope for (see CLAUDE.md). CreateWorkspace.py
        uses it to resolve a workspace's building/floor location by name.
        """
        return self.get_paged('/workspaceLocations', 'items', params=params)

    def list_devices(self, params=None):
        return self.get_paged('/devices', 'items', params=params)

    def delete_device(self, device_id):
        return self.delete(f'/devices/{device_id}')

    def create_activation_code(self, workspace_id=None, person_id=None):
        """Generate a device activation code for a workspace or person.

        POST /devices/activationCode. Distinct from the direct MAC-based
        registration AddDevicesWorkspaces.py performs with POST /devices;
        an activation code is what a user types into an unprovisioned
        device to claim it.
        """
        payload = {}
        if workspace_id:
            payload['workspaceId'] = workspace_id
        if person_id:
            payload['personId'] = person_id
        return self.post('/devices/activationCode', payload)

    # ------------------------------------------------------------------ numbers

    def list_numbers(self, params=None):
        """PSTN numbers in the org (GET /telephony/config/numbers)."""
        return self.get_paged('/telephony/config/numbers', 'phoneNumbers', params=params)

    def add_numbers(self, location_id, numbers, number_type='DID',
                    number_usage_type='NONE', state='ACTIVE'):
        """Add numbers to a location (POST .../locations/{id}/numbers).

        Based on AddNumbersToLocation.py.
        """
        payload = {
            'phoneNumbers': list(numbers),
            'numberType': number_type,
            'numberUsageType': number_usage_type,
            'state': state,
        }
        return self.post(f'/telephony/config/locations/{location_id}/numbers', payload)

    def delete_numbers(self, location_id, numbers):
        """Remove numbers from a location (DELETE with a body needs a raw call)."""
        url = self._url(f'/telephony/config/locations/{location_id}/numbers')
        try:
            resp = self.session.delete(url, json={'phoneNumbers': list(numbers)},
                                       timeout=self.timeout)
        except requests.RequestException as e:
            return _result(False, error=f'Request failed: {e}')
        if resp.status_code >= 400:
            return _result(False, error=_error_text(resp))
        return _result(True, {})

    # ------------------------------------------------------------------ call queues and hunt groups

    def list_call_queues(self, params=None):
        return self.get_paged('/telephony/config/queues', 'queues', params=params)

    def get_call_queue(self, location_id, queue_id):
        return self.get(f'/telephony/config/locations/{location_id}/queues/{queue_id}')

    def create_call_queue(self, location_id, payload):
        """Create a call queue (POST .../locations/{id}/queues). Based on CreateCallQueue.py."""
        return self.post(f'/telephony/config/locations/{location_id}/queues', payload)

    def delete_call_queue(self, location_id, queue_id):
        return self.delete(f'/telephony/config/locations/{location_id}/queues/{queue_id}')

    def update_call_queue(self, location_id, queue_id, payload):
        return self.put(f'/telephony/config/locations/{location_id}/queues/{queue_id}', payload)

    def list_hunt_groups(self, params=None):
        return self.get_paged('/telephony/config/huntGroups', 'huntGroups', params=params)

    def get_hunt_group(self, location_id, group_id):
        return self.get(f'/telephony/config/locations/{location_id}/huntGroups/{group_id}')

    def create_hunt_group(self, location_id, payload):
        """Create a hunt group (POST .../locations/{id}/huntGroups). Based on CreateHuntGroup.py."""
        return self.post(f'/telephony/config/locations/{location_id}/huntGroups', payload)

    def delete_hunt_group(self, location_id, group_id):
        return self.delete(f'/telephony/config/locations/{location_id}/huntGroups/{group_id}')

    def update_hunt_group(self, location_id, group_id, payload):
        return self.put(f'/telephony/config/locations/{location_id}/huntGroups/{group_id}',
                        payload)

    def list_virtual_lines(self, params=None):
        """Virtual lines (GET /telephony/config/virtualLines), looked up by
        phoneNumber when resolving a numeric agent entry to an id.
        """
        return self.get_paged('/telephony/config/virtualLines', 'virtualLines', params=params)

    # ------------------------------------------------------------------ groups and schedules

    def list_groups(self, params=None):
        """Org user groups (GET /groups)."""
        return self.get_paged('/groups', 'groups', params=params)

    def get_group(self, group_id, include_members=False):
        params = {'includeMembers': 'true'} if include_members else None
        return self.get(f'/groups/{group_id}', params=params)

    def patch_group(self, group_id, members):
        """Replace a group's member list (PATCH /groups/{id}).

        Based on UpdateUserGroups.py, which does a full replace; callers
        wanting to add members without dropping existing ones should read
        the current member list first and pass the union.
        """
        return self.patch(f'/groups/{group_id}', {'members': list(members)})

    def list_location_schedules(self, location_id):
        return self.get_paged(f'/telephony/config/locations/{location_id}/schedules',
                              'schedules')

    # ------------------------------------------------------------------ call forwarding

    def get_person_call_forwarding(self, person_id):
        return self.get(f'/people/{person_id}/features/callForwarding')

    def set_person_call_forwarding(self, person_id, payload):
        return self.put(f'/people/{person_id}/features/callForwarding', payload)
