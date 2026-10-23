"""
RedSky (Horizon Mobility) REST client, counterpart of cucm/ucmAPI.py.

Authenticates against the RedSky auth-service and wraps the E911 geography
endpoints. Access tokens last 15 minutes; this client simply logs in again
when the token is near expiry.

Operation methods return a dict:
    {'success': bool, 'response': str, 'error': str}
Building/location creation adds 'ambiguous' (bool) and 'candidates' (list).
Networking creates add 'id' (the new object's id, when RedSky returns one).
"""

import warnings
warnings.simplefilter('ignore')

from datetime import datetime, timedelta

import requests

REDSKY_BASE_URL = 'https://api.wxc.e911cloud.com'


class RedSky:
    def __init__(self, username, password, org_id, logger=None, base_url=REDSKY_BASE_URL):
        self.username = username
        self.password = password
        self.org_id = org_id
        self.base_url = base_url
        self.logger = logger
        self.session = requests.Session()
        self.token_expiry = None
        self.login()

    def login(self):
        """POST /auth-service/login and store the bearer token. Raises on failure."""
        response = self.session.post(
            f'{self.base_url}/auth-service/login',
            json={'username': self.username, 'password': self.password},
            timeout=15)
        if not response.ok:
            raise Exception(f'RedSky login failed (HTTP {response.status_code}): {response.text}')
        token = response.json().get('accessToken')
        if not token:
            raise Exception('RedSky login response missing accessToken')
        self.session.headers['Authorization'] = f'Bearer {token}'
        self.token_expiry = datetime.utcnow() + timedelta(minutes=14, seconds=30)
        if self.logger:
            self.logger.debug('RedSky login successful for %s', self.username)

    def _request(self, method, path, **kwargs):
        if self.token_expiry and datetime.utcnow() >= self.token_expiry:
            self.login()
        return self.session.request(method, f'{self.base_url}{path}', timeout=30, **kwargs)

    def _list_paged(self, path, params):
        """Page through a list endpoint. Handles a plain array or a {'content': [...]} page."""
        items, page, page_size = [], 1, 100
        while True:
            response = self._request('GET', path, params={**params, 'page': page, 'pageSize': page_size,
                                                          'direction': 'ASC', 'searchTerm': ''})
            response.raise_for_status()
            data = response.json()
            batch = data.get('content', []) if isinstance(data, dict) else data
            items.extend(batch)
            if len(batch) < page_size:
                return items
            page += 1

    def _list_parent(self, kind, parent_id):
        return self._list_paged(f'/geography-service/{kind}/parent/{parent_id}',
                                {'sortBy': 'name', 'origin': 'default'})

    def list_buildings(self):
        """Return all buildings in the organization as raw dicts (id, name, ...)."""
        return self._list_parent('buildings', self.org_id)

    def list_locations(self, parent_id=None):
        """Return the locations directly under a Building id (default: the organization)."""
        return self._list_parent('locations', parent_id or self.org_id)

    def list_all_locations(self):
        """
        Return every location as (building_name, location) tuples: the ones directly
        under the organization (building_name '') plus those under each Building.
        """
        found = [('', loc) for loc in self.list_locations()]
        for building in self.list_buildings():
            found.extend((building.get('name', ''), loc) for loc in self.list_locations(building['id']))
        return found

    def list_network_switches(self):
        """Return all LLDP chassis (network switches) as raw dicts (id, chassisId, ...)."""
        return self._list_paged(f'/networking-service/networkSwitch/company/{self.org_id}',
                                {'sortBy': 'location'})

    def add_building(self, name, full_address, supplemental_data=''):
        """
        Create a building. POST /geography-service/buildings.

        RedSky validates the address and may answer "ambiguous" (several candidate
        addresses) or "addressInvalid" instead of creating the building.
        """
        payload = {
            'name': name,
            'parentOrganizationUnitId': self.org_id,
            'fullAddress': full_address,
            'latitude': '',
            'longitude': '',
            'supplementalData': supplemental_data,
            'origin': 'default',
        }
        result = {'success': False, 'response': '', 'error': '', 'ambiguous': False, 'candidates': []}
        try:
            response = self._request('POST', '/geography-service/buildings', json=payload)
        except requests.RequestException as e:
            result['error'] = f'Network error: {e}'
            return result
        if not response.ok:
            result['error'] = f'HTTP {response.status_code}: {response.text}'
            return result

        data = response.json()
        if data.get('ambiguous'):
            result['ambiguous'] = True
            result['candidates'] = data.get('addressList') or []
            result['error'] = 'Address is ambiguous (matches multiple candidates)'
        elif data.get('addressInvalid'):
            result['error'] = 'Address is invalid (RedSky could not validate it)'
        else:
            building = data.get('orgUnitTO') or {}
            result['success'] = True
            result['response'] = f"Created building {building.get('name', name)} (id {building.get('id', '?')})"
        return result

    def add_location(self, name, parent_id, full_address=None, info=None, alternate_id=None,
                     callback_number=None, html_link_url=None, html_link_name=None,
                     org_name_override=None):
        """
        Create a location. POST /geography-service/locations.

        parent_id is a Building id, or the org id for tenants without a Buildings layer.
        Optional fields that are None or blank are left out of the request.
        Like buildings, RedSky may answer "ambiguous" or "addressInvalid" instead of creating it.
        """
        payload = {'name': name, 'organizationUnitId': parent_id}
        optional = {
            'fullAddress': full_address, 'info': info, 'alternateId': alternate_id,
            'callbackNumber': callback_number, 'htmlLinkUrl': html_link_url,
            'htmlLinkName': html_link_name, 'orgNameOverride': org_name_override,
        }
        payload.update({k: v for k, v in optional.items() if v})

        result = {'success': False, 'response': '', 'error': '', 'ambiguous': False, 'candidates': []}
        try:
            response = self._request('POST', '/geography-service/locations', json=payload)
        except requests.RequestException as e:
            result['error'] = f'Network error: {e}'
            return result
        if not response.ok:
            result['error'] = f'HTTP {response.status_code}: {response.text}'
            return result

        data = response.json()
        if data.get('ambiguous'):
            result['ambiguous'] = True
            result['candidates'] = data.get('addressList') or []
            result['error'] = 'Address is ambiguous (matches multiple candidates)'
        elif data.get('addressInvalid'):
            result['error'] = 'Address is invalid (RedSky could not validate it)'
        elif not data.get('erlTO'):
            result['error'] = 'Response missing erlTO'
        else:
            erl = data['erlTO']
            result['success'] = True
            result['response'] = f"Created location {erl.get('name', name)} (id {erl.get('id', '?')})"
        return result

    def _create(self, path, payload, label, params=None):
        """POST a create request. Returns {'success', 'response', 'error'} with the new id when given."""
        result = {'success': False, 'response': '', 'error': '', 'id': ''}
        try:
            response = self._request('POST', path, json=payload, params=params)
        except requests.RequestException as e:
            result['error'] = f'Network error: {e}'
            return result
        if not response.ok:
            result['error'] = f'HTTP {response.status_code}: {response.text}'
            return result
        try:
            data = response.json()
        except ValueError:
            data = {}
        result['id'] = data.get('id', '') if isinstance(data, dict) else ''
        result['success'] = True
        result['response'] = f"Created {label}" + (f" (id {result['id']})" if result['id'] else '')
        return result

    @staticmethod
    def _optional(payload, **fields):
        payload.update({k: v for k, v in fields.items() if v not in (None, '')})
        return payload

    def add_network_switch(self, chassis_id, location_id=None, description=None):
        """Create an LLDP chassis. POST /networking-service/networkSwitch."""
        payload = self._optional({'companyId': self.org_id, 'chassisId': chassis_id},
                                 description=description, locationId=location_id)
        return self._create('/networking-service/networkSwitch', payload, f'switch {chassis_id}',
                            params={'companyId': self.org_id})

    def add_network_switch_port(self, port_id, network_switch_id, location_id=None, description=None):
        """Create an LLDP port on a chassis. POST /networking-service/networkSwitchPort."""
        payload = self._optional({'portId': port_id, 'networkSwitchId': network_switch_id},
                                 description=description, erlId=location_id)
        return self._create('/networking-service/networkSwitchPort', payload, f'switch port {port_id}')

    def add_bssid(self, bssid, location_id=None, description=None, masking=None):
        """Create a BSSID. POST /networking-service/bssid. masking is True, False or None."""
        payload = self._optional({'bssid': bssid, 'orgId': self.org_id},
                                 locationId=location_id, description=description)
        if masking is not None:
            payload['bssidMasking'] = masking
        return self._create('/networking-service/bssid', payload, f'BSSID {bssid}')

    def add_ip_range(self, ip_low, ip_high, location_id=None, description=None):
        """Create a private IP range. POST /networking-service/ipRange."""
        payload = self._optional({'ipAddressLow': ip_low, 'ipAddressHigh': ip_high},
                                 description=description, locationId=location_id)
        return self._create('/networking-service/ipRange', payload, f'IP range {ip_low}-{ip_high}',
                            params={'companyId': self.org_id})

    def add_public_ip_range(self, ip_low, ip_high, description=None):
        """Create a public (trusted) IP range. POST /networking-service/publicIpRange."""
        payload = self._optional({'companyId': self.org_id, 'ipAddressLow': ip_low, 'ipAddressHigh': ip_high},
                                 description=description)
        return self._create('/networking-service/publicIpRange', payload, f'public IP range {ip_low}-{ip_high}',
                            params={'companyId': self.org_id})

    def list_alert_types(self):
        """GET /admin-service/alert-type. Returns {machine name: display text}."""
        response = self._request('GET', '/admin-service/alert-type')
        response.raise_for_status()
        return response.json()

    def list_alert_templates(self, alert_type=None):
        """Return the organization's alert templates plus the system ones (skipped if the account lacks access), optionally for one alert type."""
        params = {'sortBy': 'name'}
        if alert_type:
            params['alertType'] = alert_type
        templates = self._list_paged(f'/admin-service/alert-template/company/{self.org_id}', params)
        try:
            templates += self._list_paged('/admin-service/alert-template/system', params)
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 403:
                raise
            if self.logger:
                self.logger.warning('System alert templates are not available to this account (HTTP 403); '
                                    'only the organization\'s own templates can be selected')
        return templates

    def add_alert_subscription(self, name, alert_type, template_id=None, emails=(), sms=(),
                               timezone=None, all_corporate=False, all_personal=False):
        """
        Create an alert subscription. POST /admin-service/alertSubscription.

        alert_type is a (name, text) tuple from list_alert_types(). emails and sms are lists of strings.
        """
        payload = self._optional(
            {'name': name, 'companyId': self.org_id,
             'alertTypeTO': {'name': alert_type[0], 'text': alert_type[1]},
             'emailRecipients': [{'email': e} for e in emails],
             'smsRecipients': [{'phoneNumber': n} for n in sms],
             'allCorporateLocations': bool(all_corporate), 'allPersonalLocations': bool(all_personal)},
            templateId=template_id, timezone=timezone)
        return self._create('/admin-service/alertSubscription', payload, f'alert subscription {name}')

    def set_alert_subscription_filters(self, subscription_id, filters):
        """
        Scope a subscription. POST /admin-service/alertSubscription/{id}/filters.

        filters is a list of (ou_id, filter_type) tuples; filter_type is BUILDING or LOCATION.
        """
        payload = [{'subscriptionId': subscription_id, 'ouId': ou_id, 'filterType': filter_type}
                   for ou_id, filter_type in filters]
        return self._create(f'/admin-service/alertSubscription/{subscription_id}/filters', payload,
                            f'{len(payload)} filter(s)')

    def list_alert_subscriptions(self):
        """Return the organization's alert subscriptions as raw dicts (id, name, alertTypeTO, ...)."""
        return self._list_paged(f'/admin-service/alertSubscription/company/{self.org_id}',
                                {'sortBy': 'name'})

    def list_alert_subscription_filters(self, subscription_id):
        """Return a subscription's scope filters as raw dicts (ouId, filterType)."""
        return self._list_paged(f'/admin-service/alertSubscription/{subscription_id}/filters',
                                {'sortBy': 'ouId'})
