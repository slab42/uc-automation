#!/usr/bin/env python3
"""
Cisco Unity Connection (CUC) REST API wrapper.

Counterpart of cucm/ucmAPI.py for the CUC scripts. Wraps a requests.Session
against https://<server>/vmrest with basic auth, XML responses, retries and
pagination, and exposes the handful of operations the scripts need.

Every public method returns the same dict shape as ucmAPI.AXL:
    {'success': bool, 'response': <payload>, 'error': str}

The wrapper never logs and never prints; callers log the results. Passwords
are held only on the session's auth object and never appear in any return
value or exception message produced here.

Usage from a script in this folder (cwd is cuc/ when run via main.py):
    from cucAPI import CUC
    cuc = CUC(username, password, server, version)
    result = cuc.find_user_by_extension('2001')
    if result['success']:
        user = result['response']          # dict of <User> child elements
"""

import math

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry
from lxml import etree

DEFAULT_PAGE_SIZE = 2000
DEFAULT_TIMEOUT = 60


def element_to_dict(element):
    """Return {child.tag: child.text} for the direct children of an lxml element."""
    return {child.tag: (child.text or '').strip() if child.text is not None else '' for child in element}


def _result(success, response=None, error=''):
    """Build the standard result dict."""
    return {'success': success, 'response': response if response is not None else '', 'error': error}


class CUC:
    """Thin client for the CUC vmrest API."""

    def __init__(self, username, password, server, version=None, timeout=DEFAULT_TIMEOUT, page_size=DEFAULT_PAGE_SIZE):
        """
        Args:
            username (str): CUC admin username
            password (str): CUC admin password (never stored anywhere but the session auth)
            server (str): CUC server IP or hostname
            version (str): CUC version string from clusters.csv (informational)
            timeout (int): per-request timeout in seconds
            page_size (int): rowsPerPage used for paged list calls
        """
        self.server = server
        self.version = version
        self.timeout = timeout
        self.page_size = page_size
        self.base_url = f'https://{server}/vmrest'

        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, password)
        self.session.headers.update({'Accept': 'application/xml', 'Content-Type': 'application/xml'})
        retry = Retry(
            total=4, connect=4, read=4, backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(['GET']),
            respect_retry_after_header=True,
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    # ------------------------------------------------------------------ low level

    def _url(self, path):
        """Accept '/vmrest/...', '/users/...', 'users/...' or a full https URL."""
        if path.startswith('http'):
            return path
        if path.startswith('/vmrest'):
            return f'https://{self.server}{path}'
        return f"{self.base_url}/{path.lstrip('/')}"

    def get(self, path, params=None):
        """GET and parse XML. Returns result dict whose response is the lxml root element."""
        try:
            response = self.session.get(self._url(path), params=params, verify=False, timeout=self.timeout)
            if not response.ok:
                return _result(False, error=f'HTTP {response.status_code} on {response.url}: {response.text[:500]}')
            return _result(True, etree.fromstring(response.content))
        except requests.exceptions.RequestException as e:
            return _result(False, error=f'API request failed: {e}')
        except etree.XMLSyntaxError as e:
            return _result(False, error=f'Error parsing XML response: {e}')

    def delete(self, path):
        """DELETE a resource. Success on HTTP 200/204."""
        try:
            response = self.session.delete(self._url(path), verify=False, timeout=self.timeout)
            if response.status_code in (200, 204):
                return _result(True, f'Deleted {path}')
            return _result(False, error=f'HTTP {response.status_code}: {response.text[:500]}')
        except requests.exceptions.RequestException as e:
            return _result(False, error=f'API request failed: {e}')

    def get_paged(self, path, tag, params=None):
        """
        GET every page of a list resource.

        Args:
            path (str): resource path, e.g. 'handlers/callhandlers'
            tag (str): element tag to collect, e.g. 'Callhandler'
            params (dict): extra query params (e.g. {'query': '(DtmfAccessId is 2001)'})

        Returns:
            result dict; response is a list of dicts (one per element), de-duplicated on ObjectId.
        """
        items = []
        seen = set()
        page_number = 1
        total_reported = None
        while True:
            page_params = dict(params or {})
            page_params.update({'rowsPerPage': self.page_size, 'pageNumber': page_number})
            page = self.get(path, params=page_params)
            if not page['success']:
                return page
            root = page['response']

            if total_reported is None:
                total_text = root.get('total')
                total_reported = int(total_text) if total_text and total_text.isdigit() else None

            elements = root.findall(f'.//{tag}')
            if not elements:
                break

            new_ids = 0
            for element in elements:
                item = element_to_dict(element)
                object_id = item.get('ObjectId', '')
                if object_id:
                    if object_id in seen:
                        continue
                    seen.add(object_id)
                    new_ids += 1
                items.append(item)

            if len(elements) < self.page_size:
                break
            if total_reported is not None and len(items) >= total_reported:
                break
            if new_ids == 0:
                return _result(False, items, 'Server repeated a page with no new ObjectIds; pagination not honored')
            if total_reported is not None and page_number >= math.ceil(total_reported / self.page_size):
                break
            page_number += 1

        return _result(True, items)

    # ------------------------------------------------------------------ users / mailboxes

    def find_user_by_extension(self, extension):
        """
        Look up a user by DtmfAccessId (primary extension).

        Returns:
            result dict; response is the user dict (keys are <User> child tags such as
            Alias, DisplayName, DtmfAccessId, ObjectId, URI). Fails if no exact match.
        """
        extension = str(extension).strip()
        result = self.get_paged('users', 'User', params={'query': f'(DtmfAccessId is {extension})'})
        if not result['success']:
            return result
        for user in result['response']:
            if user.get('DtmfAccessId') == extension:
                return _result(True, user)
        return _result(False, error=f'No user found with DtmfAccessId: {extension}')

    def get_mailbox_attributes(self, user_uri):
        """
        Fetch /mailboxattributes for a user URI (the URI field from find_user_by_extension).

        Returns:
            result dict; response is a dict of MailboxAttributes children (ByteSize, WarningQuota, ...).
        """
        result = self.get(f'{user_uri}/mailboxattributes')
        if not result['success']:
            return result
        root = result['response']
        if root.tag != 'MailboxAttributes':
            root = root.find('.//MailboxAttributes')
            if root is None:
                return _result(False, error='MailboxAttributes element not found in response')
        return _result(True, element_to_dict(root))

    def get_user_mailbox_usage(self, extension):
        """
        Convenience: user lookup + mailbox attributes in one call.

        Returns:
            result dict; response is
            {'dtmfAccessId', 'alias', 'displayName', 'uri', 'byteSize', 'sizeMb', 'mailbox': <raw attributes dict>}
        """
        user_result = self.find_user_by_extension(extension)
        if not user_result['success']:
            return user_result
        user = user_result['response']
        user_uri = user.get('URI', '')
        if not user_uri:
            return _result(False, error=f"No URI found for user {user.get('Alias', extension)}")

        mailbox_result = self.get_mailbox_attributes(user_uri)
        if not mailbox_result['success']:
            return mailbox_result
        mailbox = mailbox_result['response']

        try:
            byte_size = int(mailbox.get('ByteSize') or 0)
        except ValueError:
            byte_size = 0

        return _result(True, {
            'dtmfAccessId': user.get('DtmfAccessId', str(extension)),
            'alias': user.get('Alias', ''),
            'displayName': user.get('DisplayName', ''),
            'uri': user_uri,
            'byteSize': byte_size,
            'sizeMb': round(byte_size / (1024 * 1024), 2),
            'mailbox': mailbox,
        })

    def delete_user(self, user_uri):
        """Delete a user (and therefore its mailbox) by URI."""
        return self.delete(user_uri)

    # ------------------------------------------------------------------ call handlers

    def list_call_handlers(self):
        """
        Return every call handler (system, subscriber and non-subscriber) as raw dicts.

        Callers filter on DisplayName / RecipientSubscriberObjectId as needed.
        """
        return self.get_paged('handlers/callhandlers', 'Callhandler')

    def get_menu_entries(self, handler_object_id):
        """Return the MenuEntry dicts for one call handler."""
        result = self.get(f'handlers/callhandlers/{handler_object_id}/menuentries')
        if not result['success']:
            return result
        return _result(True, [element_to_dict(e) for e in result['response'].findall('.//MenuEntry')])

    def delete_call_handler(self, object_id):
        """Delete a call handler by ObjectId."""
        return self.delete(f'handlers/callhandlers/{object_id}')
