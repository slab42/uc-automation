#!/usr/bin/env python3

"""
Class of API calls to a Cisco Call Manager

"""

from zeep import Client, Settings
from zeep.cache import SqliteCache
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
from zeep.exceptions import Fault
from zeep.helpers import serialize_object
from requests import Session
from requests.auth import HTTPBasicAuth
# from lxml import etree
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  


class AXL(object):
    """
    The AXL class sets up the connection to the call manager with methods for configuring UCM.
    """

    def __init__(self, username, password, wsdl, cucm, cucm_version):
        """
        :param username: axl username
        :param password: axl password
        :param wsdl: wsdl file location
        :param cucm: UCM IP address
        :param cucm_version: UCM version
        """
        self.username = username
        self.password = password
        self.wsdl = wsdl
        self.cucm = cucm
        self.cucm_version = cucm_version

        self.session = Session()
        self.session.verify = False
        self.session.auth = HTTPBasicAuth(self.username, self.password)
        self.transport = Transport(cache=SqliteCache(), session=self.session, timeout=10)
        # strict=False is not always necessary, but it allows zeep to parse imperfect XML
        self.settings = Settings(strict=False, xml_huge_tree=True)
        self.history = HistoryPlugin()
        self.client = Client(wsdl=self.wsdl, transport=self.transport, settings=self.settings, plugins=[self.history])
        self.service = self.client.create_service('{http://www.cisco.com/AXLAPIService/}AXLAPIBinding', 'https://{0}:8443/axl/'.format(cucm))


    def add_advertised_patterns(self, **kwargs):
        """Add Advertised Patterns
        :param description: Description of Patter
        :param pattern: Pattern String
        :param patternType: 'Enterprise Number' or '+E.164 Number'
        :param hostedRoutePSTNRule: 'No PSTN', 'Use pattern', or 'Specify'
        :param pstnFailStrip: Number of Digits to Strip for PSTN Failover
        :param pstnFailPrepend: String Digits to Prepend for PSTN Failover
        :return result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.addAdvertisedPatterns(kwargs)
            result['success'] = True
            result['response'] = 'Advertisted Pattern Added Successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_advertised_patterns(self, pattern):
        """Remove Advertised Pattern
        :param pattern: Pattern String
        :return result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeAdvertisedPatterns(pattern=pattern)
            result['success'] = True
            result['response'] = f'{pattern} Advertised Pattern Removed Successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_advertised_patterns(self):
        """List all Advertised Patterns
        :return: result dictionary with list of advertised patterns
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listAdvertisedPatterns(
                searchCriteria={'pattern': '%'},
                returnedTags={
                    'description': True,
                    'pattern': True,
                    'patternType': True,
                    'hostedRoutePSTNRule': True,
                    'pstnFailStrip': True,
                    'pstnFailPrepend': True
                })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['advertisedPatterns']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def add_audio_codec_preference_list(self, name, codec_list, description=''):
        """Add Audio Codec Preference List
        :param name: Name of the codec preference list
        :param codec_list: List of codecs in priority order
        :param description: Description of the codec preference list
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
            'name': name,
            'description': description,
            'codecsInList': {'codecNames': codec_list},
        }

        try:
            self.service.addAudioCodecPreferenceList(request)
            result['success'] = True
            result['response'] = f'Audio Codec Preference List "{name}" added successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def add_Calling_Search_Space(self,
                                 name,
                                 description='',
                                 members=[]):
        """
        Add a Calling search space
        :param name: Name of the CSS to add
        :param description: Calling search space description
        :param members: A list of partitions to add to the CSS
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
            'name': name,
            'description': description,
            'members': {'member': []},
        }

        if members:
            [request['members']['member'].append({'routePartitionName': i,'index': members.index(i) + 1}) for i in members]

        try:
            self.service.addCss(request)
            result['success'] = True
            result['response'] = f'CSS successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def add_Device_Pool(self, 
                        name='', 
                        cm_group='Default', 
                        date_time_group='CMLocal', 
                        region='Default', 
                        location='', 
                        physical_location='', 
                        route_groups={}, 
                        media_resource_group_list='', 
                        srst='Disable', 
                        deviceMobilityGroupName='', 
                        mobilityCssName='', 
                        network_locale=''):

        """
        Add a device pool
        :param name: Device pool name
        :param cm_group: CM Group name
        :param date_time_group: Date time group name
        :param region: Region name
        :param location: Location name
        :param physicalLocationName: Physical location name
        :param route_group: {Dictionary of Route group names}
        :param media_resource_group_list: Media resource group list name
        :param srst: SRST name
        :param deviceMobilityGroupName: Device Mobiltiy Group name
        :param mobility CssName: Device Mobility Calling Search Space name
        :param network_locale: Network locale name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
            'name': name,
            'callManagerGroupName': cm_group,
            'dateTimeSettingName': date_time_group,
            'regionName': region,
            'locationName': location,
            'physicalLocationName': physical_location, 
            'localRouteGroup': [],
            'mediaResourceListName': media_resource_group_list,
            'srstName': srst,
            'deviceMobilityGroupName': deviceMobilityGroupName, 
            'mobilityCssName': mobilityCssName,
            'networkLocale': network_locale,
        }

        if route_groups:
            [request['localRouteGroup'].append({'name': key, 'value': value}) for key, value in route_groups.items()]

        try:
            self.service.addDevicePool(request)
            result['success'] = True
            result['response'] = f'Device Pool successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def add_Device_Mobility_Info(self, 
                            name='', 
                            ipv4subnet='', 
                            ipv4mask='', 
                            dp_members=[]):
        """
        Add Device Mobility Info
        :param name: Device Mobility Info name
        :param ipv4subnet: CM Group name
        :param ipv4mask: Date time group name
        :param dp_members: Region name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
            'name': name,
            'subNetDetails': {'ipv4SubNetDetails':{'ipv4Subnet': ipv4subnet,'ipv4SubNetMaskSz': ipv4mask}}, 
            'members': {'member': []}
        }
        
        # Must index and order the list of members for WSDL.
        if dp_members:
            [request['members']['member'].append({'devicePoolName': dp}) for dp in dp_members]

        try:
            self.service.addDeviceMobility(request)
            result['success'] = True
            result['response'] = f'Device Mobility Info successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    
    
    def add_Route_Pattern(self,
                      pattern='',
                      description='',
                      routePartitionName='',
                      gatewayRouteList='',
                      blockEnable=False,
                      useCallingPartyPhoneMask='Default',
                      dialPlanName=None,
                      digitDiscardInstructionName=None,
                      networkLocation='OnNet',
                      prefixDigitsOut=None,
                      routeFilterName=None):
        """
        Add a route pattern
        :param pattern: Route pattern digit string
        :param description: Route pattern description
        :param routePartitionName: Name of the route partition to place the pattern in
        :param gatewayRouteList: Name of the route list (gateway destination) for the pattern
        :param blockEnable: Block this pattern
        :param useCallingPartyPhoneMask: 'Default', 'On', or 'Off'
        :param dialPlanName: Dial plan name (mandatory for patterns with @)
        :param digitDiscardInstructionName: Digit discard instruction name
        :param networkLocation: 'OnNet' or 'OffNet'
        :param prefixDigitsOut: Digits to prefix on the outbound call
        :param routeFilterName: Route filter name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
                'pattern': pattern,
                'description': description,
                'routePartitionName': routePartitionName,
                'blockEnable': blockEnable,
                'useCallingPartyPhoneMask': useCallingPartyPhoneMask,
                'dialPlanName': dialPlanName,
                'digitDiscardInstructionName': digitDiscardInstructionName,
                'networkLocation': networkLocation,
                'prefixDigitsOut': prefixDigitsOut,
                'routeFilterName': routeFilterName,
                'destination': {'routeListName': gatewayRouteList}
        }

        try:
            self.service.addRoutePattern(request)
            result['success'] = True
            result['response'] = f'Route Pattern successfully added: {pattern}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Route_Pattern(self,
                      pattern='',
                      routePartitionName='',
                      dialPlanName=None,
                      routeFilterName=None):
        """
        Remove a route pattern
        :param pattern: Route pattern digit string
        :param routePartitionName: Name of the route partition the pattern is in
        :param dialPlanName: Dial plan name (mandatory for patterns with @)
        :param routeFilterName: Route filter name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
                'pattern': pattern,
                'routePartitionName': routePartitionName,
                'dialPlanName': dialPlanName,
                'routeFilterName': routeFilterName,
        }

        try:
            self.service.removeRoutePattern(**request)
            result['success'] = True
            result['response'] = f'Route Pattern successfully removed: {pattern}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def add_Route_Partition(self,
                      name='',
                      description='',
                      time_schedule_name='All the time'):
        """
        Add a partition
        :param name: Name of the partition to add
        :param description: Partition description
        :param time_schedule_name: Name of the time schedule to use
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
                'name': name,
                'description': description,
                'timeScheduleIdName': time_schedule_name
        }

        try:
            self.service.addRoutePartition(request)
            result['success'] = True
            result['response'] = f'Partition successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    
    
    # def add_Phone(self, phone):
    #     """
    #     Add new phone
    #     :param name:
    #     :param description
    #     :param product
    #     :param phoneTemplateName
    #     :param protocol
    #     :param protocolSide
    #     :param class
    #     :param devicePoolName
    #     :param locationName
    #     :param callingSearchSpaceName
    #     :param subscribeCallingSearchSpaceName
    #     :param securityProfileName
    #     :param sipProfileName
    #     :param ownerUserName
    #     :param primaryPhoneName
    #     :param mediaResourceListName
    #     :param networkHoldMohAudioSourceId
    #     :param userHoldMohAudioSourceId
    #     :param commonPhoneConfigName
    #     :param presenceGroupName
    #     :param useTrustedRelayPoint
    #     :param builtInBridgeStatus
    #     :param packetCaptureMode
    #     :param certificateOperation
    #     :param deviceMobilityMode
    #     :param lines: dictionary of lists of lines
    #     :return result dictionary
    #     """
    #     result = {
    #         'success': False,
    #         'response': '',
    #         'error': '',
    #     }
    #     try:
    #         self.service.addPhone(phone)
    #         result['success'] = True
    #         result['response'] = 'Phone successfully added'
    #     except Fault as error:
    #         result['response'] = 'ERROR'
    #         result['error'] = error.message
    #     return result

    
    def add_Location(self, 
                    name='', 
                    within_audio_bw=512, 
                    within_video_bw=-1, 
                    within_immersive_kbits=-1):

        """
        Add a location
        :param name: Name of the location to add
        :param within_audio_bw: ucm 10
        :param within_video_bw: ucm 10
        :param within_immersive_kbits: ucm 10
        :return: result dictionary
        """

        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {'name': name,
            'withinAudioBandwidth': within_audio_bw,
            'withinVideoBandwidth': within_video_bw,
            'withinImmersiveKbits': within_immersive_kbits,
            'betweenLocations': {'betweenLocation': {'locationName': 'Hub_None', 'weight': '50', 'audioBandwidth': '0', 'videoBandwidth': '0', 'immersiveBandwidth':'0'}}
        }

        try:
            self.service.addLocation(request)
            result['success'] = True
            result['response'] = f'Location successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def add_Physical_Location(self, name='', description=''):
        """
        Add a physical location
        :param name: Name of the physical to add
        :param description: Physical Location description such as address
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
            'name': name, 
            'description': description
        }

        try:
            self.service.addPhysicalLocation(request)
            result['success'] = True
            result['response'] = f'Physical Location successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def add_Region(self, region, codec_preference_list='', max_audio_bit_rate=''):
        """
        Add a region
        :param region: Name of the region to add
        :param codec_preference_list: Audio codec preference list name (optional)
        :param max_audio_bit_rate: Maximum audio bit rate (optional)
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {'name': region}
        if codec_preference_list:
            request['audioCodecPreferenceListName'] = codec_preference_list
        if max_audio_bit_rate:
            request['maxAudioBitRate'] = max_audio_bit_rate

        try:
            self.service.addRegion(request)
            result['success'] = True
            result['response'] = f'Region successfully added: {region}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def add_Media_Resource_Group_List(self, name, members=[]):
        """
        Add a media resource group list
        :param name: Media resource group list name
        :param members: A list of members
        :return:
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {
            'name': name,
            'members': {'member': []}
        }
        
        # Must index and order the list of members for WSDL.
        if members:
            [request['members']['member'].append({'order': members.index(i),'mediaResourceGroupName': i}) for i in members]

        try:
            self.service.addMediaResourceList(request)
            result['success'] = True
            result['response'] = f'MRGL successfully added: {name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def do_DeviceLogin (self, deviceName, loginDuration, profileName, userId):
        """
        Do Device Login
        :param deviceName:
        :param userId:
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.doDeviceLogin(deviceName=deviceName, loginDuration=loginDuration, profileName=profileName, userId=userId)
            result['success'] = True
            result['response'] = 'User Logged In Successfully'
            # result['response'] = resp['return']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def debug_get_phone(self, device_name):
        """
        Debug method to see full phone object structure
        :param device_name: Device name/ID
        :return: Full phone object response
        """
        try:
            phone_resp = self.service.getPhone(name=device_name)
            return serialize_object(phone_resp)
        except Exception as e:
            return {'error': str(e)}

    def check_device_login(self, device_name):
        """
        Check if a device has a user logged in via Extension Mobility
        :param device_name: Device name/ID (e.g., SEPDC0539FB8FA2)
        :return: result dictionary with logged_in status and user info
        """
        result = {
            'success': False,
            'logged_in': False,
            'user': None,
            'error': '',
        }
        try:
            phone_resp = self.service.getPhone(name=device_name)

            # Navigate through response structure safely
            if phone_resp is None:
                result['error'] = 'No response from CUCM'
                return serialize_object(result)

            # Convert zeep response object to dict
            phone_resp = serialize_object(phone_resp)

            # Try to get phone data from response
            if not isinstance(phone_resp, dict) or 'return' not in phone_resp:
                result['error'] = f'Unexpected response structure'
                return serialize_object(result)

            if 'phone' not in phone_resp['return']:
                result['error'] = f'No phone data in response'
                return serialize_object(result)

            phone_data = phone_resp['return']['phone']

            # Check if there's an EM user logged in via loginUserId field
            if phone_data and isinstance(phone_data, dict):
                login_user = phone_data.get('loginUserId')
                if login_user:
                    result['logged_in'] = True
                    result['user'] = login_user
                    result['success'] = True
                else:
                    result['success'] = True
                    result['logged_in'] = False
            else:
                result['success'] = True
                result['logged_in'] = False

        except Fault as error:
            # Get more details from the fault
            fault_str = str(error)
            if hasattr(error, 'detail'):
                fault_str += f" - Detail: {str(error.detail)}"
            result['error'] = f'AXL Fault: {fault_str}'
        except Exception as error:
            result['error'] = f'Error: {type(error).__name__}: {str(error)}'

        result = serialize_object(result)
        return result

    def get_CCMVersion(self):
        '''
        Get the version of CUCM. Can be used for connectivity check.
        :return: Full CUCM Version
        '''
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            resp = self.service.getCCMVersion()
            result['success'] = True
            result['response'] = resp['return']['componentVersion']['version']
        except Fault as error:
            result['response'] = 'ERROR'
            fault_str = str(error)
            if hasattr(error, 'detail'):
                detail_str = str(error.detail)
                if 'HTTP Status 401' in detail_str:
                    fault_str = 'Authentication failed: Check AXL credentials'
                else:
                    fault_str += f" - {detail_str}"
            result['error'] = fault_str
        result = serialize_object(result)
        return result
    

    def get_Device_Pool(self, name):
        """
        Get Device Pool Parameters
        :param name: Device Pool to search for
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        returnedTags={
                        'name' : '',
                        'regionName' : '',
                        'dateTimeSettingName' : '',
                        'callManagerGroupName' : '',
                        'mediaResourceListName' : '',
                        'networkLocale' : '',
                        'srstName' : '',
                        'locationName' : '',
                        'mobilityCssName' : '',
                        'physicalLocationName' : '',
                        'deviceMobilityGroupName' : '',
                        'localRouteGroup' : ''
        }

        try:
            resp = self.service.getDevicePool(name=name, returnedTags=returnedTags)
            result['success'] = True
            result['response'] = resp['return']['devicePool']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def get_Line(self, **args):
        """
        Get Line Parameters
        :param pattern: DN to search for
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        returnedTags={
                        'pattern' : '',
                        'description' : '',
                        'usage' : '',
                        'routePartitionName' : '',
                        'callForwardAll' : '',
                        'callPickupGroupName' : '',
                        'networkHoldMohAudioSourceId' : '',
                        'userHoldMohAudioSourceId' : '',
                        'alertingName' : '',
                        'asciiAlertingName' : '',
                        'shareLineAppearanceCssName': '',
                        'voiceMailProfileName' : '',
                        'directoryURIs' : '',
                        'enterpriseAltNum' : '',
                        'useEnterpriseAltNum' : '',
                        'e164AltNum' : '',
                        'useE164AltNum' : '',
                        'associatedDevices' : ''

        }

        try:
            resp = self.service.getLine(**args, returnedTags=returnedTags)
            # print(resp)
            result['success'] = True
            result['response'] = resp['return']['line']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    
    
    def get_MediaResourceList(self, mrgl):
        """
        Get Media Resource Group List Memebers
        :param mrgl: MRGL to search for
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        returnedTags={
                        'name' : '',
                        'clause' : '',
                        'members' : ''
        }

        try:
            resp = self.service.getMediaResourceList(name=mrgl, returnedTags=returnedTags)
            result['success'] = True
            result['response'] = resp['return']['mediaResourceList']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def get_Phone(self, **args):
        """
        Get device profile parameters
        :param phone: profile name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            resp = self.service.getPhone(**args)
            result['success'] = True
            result['response'] = resp['return']['phone']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def get_User(self, user_id):
        """
        Get user parameters
        :param user_id: profile name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            resp = self.service.getUser(userid=user_id)
            result['success'] = True
            result['response'] = resp['return']['user']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def list_Line(self, searchFor, searchString):
        """
        Get Line Details details
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listLine(
                    {searchFor : f'{searchString}'}, returnedTags={
                        'pattern' : '',
                        'description' : '',
                        'routePartitionName' : '',
                        'alertingName' : ''
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['line']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
        
        
    def list_Phone(self):
        """
        Get phone details
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            resp = self.service.listPhone(
                    {'name': '%'}, returnedTags={
                        'name': '',
                        'product': '',
                        'protocol': '',
                        'description': '',
                        'locationName': '',
                        'devicePoolName': '',
                        'phoneTemplateName': '',
                        'ownerUserName' : ''
                    })['return']['phone']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    
 

    def list_Phone_search_desc(self,searchString):
        """
        Get phone details
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            resp = self.service.listPhone(
                    {'description': f'%{searchString}%'}, returnedTags={
                        'name': '',
                        'product': '',
                        'protocol': '',
                        'description': '',
                        'locationName': '',
                        'ownerUserName' : ''
                    })['return']['phone']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    
    
    def remove_Calling_Search_Space(self, name):
        """
        Remove a Calling Search Space
        :return: Object ID of removed CSS
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeCss(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def remove_Cti_Route_Point(self, deviceName):
        """
        Remove a CTI RP
        :return: Object ID of removed CTI Route Point
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeCtiRoutePoint(name=deviceName)
            result['success'] = True
            result['response'] = f'{deviceName} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Device_Mobility_Info(self, name):
        """
        Remove a Device Mobility Info Subnet
        :return: Object ID of removed DMI
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeDeviceMobility(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Device_Pool(self, name):
        """
        Remove a Device Pool
        :return: Object ID of removed DMI
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeDevicePool(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def update_Device_Pool(self, name, region_name):
        """
        Update Device Pool region
        :param name: Device pool name
        :param region_name: Region name to set
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.updateDevicePool(name=name, regionName=region_name)
            result['success'] = True
            result['response'] = f'Device Pool {name} updated to use region {region_name}'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Line(self, DN, PT):
        """
        Remove a DN
        :return: Object ID of removed CTI Route Point
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeLine(pattern=DN, routePartitionName=PT)
            result['success'] = True
            result['response'] = f'{DN} in {PT} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    

    def remove_Location(self, name):
        """
        Remove a Location
        :return: Object ID of removed DMI
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeLocation(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Media_Resource_Group_List(self, name):
        """
        Remove a MRGL
        :return: Object ID of removed MRGL
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeMediaResourceList(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Physical_Location(self, name):
        """
        Remove a Physical Location
        :return: Object ID of removed Physical Location
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removePhysicalLocation(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Region(self, name):
        """
        Remove a Region
        :return: Object ID of removed Region
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeRegion(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def remove_Route_Partition(self, name):
        """
        Remove a Partition
        :return: Object ID of removed Partition
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeRoutePartition(name=name)
            result['success'] = True
            result['response'] = f'{name} Removed'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def reset_Phone(self, name):
        """
        Reset a phone
        :return: Object ID of phone
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.resetPhone(name=name)
            result['success'] = True
            result['response'] = f'{name} Reset'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def update_Line(self, **args):
        """Update line
        :param uuid
        :param pattern
        :param routePartitionName
        :param callPickupGroupName
        etc - Need to fill in later
        :return result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.updateLine(**args)
            result['success'] = True
            result['response'] = 'Line successfully updated'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def update_Phone(self, **args): 
        """
        Update Phone
        :param name:
        :param description
        :param product
        :param phoneTemplateName
        :param protocol
        :param protocolSide
        :param class
        :param devicePoolName
        :param locationName
        :param callingSearchSpaceName
        :param subscribeCallingSearchSpaceName
        :param securityProfileName
        :param sipProfileName
        :param ownerUserName
        :param primaryPhoneName
        :param mediaResourceListName
        :param networkHoldMohAudioSourceId
        :param userHoldMohAudioSourceId
        :param commonPhoneConfigName
        :param presenceGroupName
        :param useTrustedRelayPoint
        :param builtInBridgeStatus
        :param packetCaptureMode
        :param certificateOperation
        :param deviceMobilityMode
        :param lines: dictionary of lists of lines
        :return result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.updatePhone(**args)
            result['success'] = True
            result['response'] = 'Phone successfully updated'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def update_TransPattern(self, **args):
        """Update Translation Pattern
        :param uuid
        :param pattern
        :param routePartitionName
        :param newRoutePartitionName
        etc
        :return result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.updateTransPattern(**args)
            result['success'] = True
            result['response'] = 'Translation successfully updated'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def update_User(self, **args):
        """
        Update end user for credentials
        :param userid: User ID
        :param password: Web interface password
        :param pin: Extension mobility PIN
        :param primaryExtension: Primary Extension
        :param associatedDevices: List of associated devices
        :param associatedGroups: List of user groups
        :param homeCluster: Home Cluster selection
        :param lineAppearanceAssociationForPresences: Line Appearance Associations
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.updateUser(**args)
            result['success'] = True
            result['response'] = f'User successfully updated'
        except Fault as error:
            result['response'] = 'ERROR'
            fault_str = str(error)
            if hasattr(error, 'detail'):
                detail_str = str(error.detail)
                if 'HTTP Status 401' in detail_str:
                    fault_str = 'Authentication failed: Check AXL credentials or permissions'
                else:
                    fault_str += f" - {detail_str}"
            result['error'] = fault_str
        result = serialize_object(result)
        return result


    def list_AarGroups(self):
        """
        Get List of AAR Groups
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listAarGroup(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['aarGroup']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_CallPickupGroup(self):
        """
        Get List of Call Pickup Groups
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listCallPickupGroup(
                    {'pattern' : f'%'}, returnedTags={
                        'pattern' : '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['callPickupGroup']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_Css(self):
        """
        Get List of Calling Search Spaces
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listCss(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                        'clause': ''
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['css']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_DevicePools(self):
        """
        Get List of Device Pools
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listDevicePool(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['devicePool']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_Locations(self):
        """
        Get List of Locations
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listLocation(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['location']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    

    def list_MediaResourceLists(self):
        """
        Get List of Media Reource Group Lists
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listMediaResourceList(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['mediaResourceList']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    
    def list_MohAudioSources(self):
        """
        Get List of Music on Hold Sources
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listMohAudioSource(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                        'sourceId' : ''
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['mohAudioSource']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_PresenceGroups(self):
        """
        Get List of Presence Groups
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listPresenceGroup(
                    {'name' : f'%'}, returnedTags={
                        'name' : ''
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['presenceGroup']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def listProcessNodes(self):
        
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        fullResp = self.service.listProcessNode({'name': '%', 'processNodeRole': 'CUCM Voice/Video'}, returnedTags={'name': ''})
        if fullResp['return'] == None:
            result['error'] = 'No Response'
            result = serialize_object(result)
            return result
        else:
            result['success'] = True
            subs = []
            nodes = fullResp['return']['processNode']
            
            # only return call processing nodes and not the enterprisewidedata node
            for node in nodes:
                    if node.name != 'EnterpriseWideData':
                        subs.append(node.name)
            result['response'] = subs
            result = serialize_object(result)
            return result


    def list_RoutePartitions(self):
        """
        Get List of Route Partitions
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listRoutePartition(
                    {'name' : f'%'}, returnedTags={
                        'name' : ''
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['routePartition']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_route_patterns(self):
        """List all Route Patterns
        :return: result dictionary with list of route patterns
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listRoutePattern(
                searchCriteria={'pattern': '%'},
                returnedTags={
                    'description': True,
                    'pattern': True,
                    'routePartitionName': True,
                })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['routePattern']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_VoiceMailProfiles(self):
        """
        Get List of Route Partitions
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listVoiceMailProfile(
                    {'name' : f'%'}, returnedTags={
                        'name' : ''
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['voiceMailProfile']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result
    

    def execute_sql_update(self, query):
        """
        Execute SQL update
        :param query: SQL Update to execute
        :return: result dictionary
        """
        resp = self.service.executeSQLUpdate(query)
        resp = serialize_object(resp)

        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        if resp.get('return') == None:
            result['response'] = 'Error'
            result['error'] = resp
            result = serialize_object(result)
            return result
        else:
            result['success'] = True
            result['response'] = resp
            result = serialize_object(result)
            return result

    def execute_sql_query(self, query):
        """
        Execute SQL query and return results
        :param query: SQL query to execute
        :return: result dictionary with list of row dicts
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }
        try:
            resp = self.service.executeSQLQuery(sql=query)
            resp = serialize_object(resp)
            if resp.get('return') == None or resp['return'].get('row') is None:
                result['success'] = True
                result['response'] = []
            else:
                rows = resp['return']['row']
                if not isinstance(rows, list):
                    rows = [rows]

                # Handle nested lists and extract values from lxml Elements
                processed_rows = []
                for row in rows:
                    if isinstance(row, list):
                        for item in row:
                            processed_rows.append(self._extract_element_value(item))
                    else:
                        processed_rows.append(self._extract_element_value(row))

                result['success'] = True
                result['response'] = processed_rows
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def _extract_element_value(self, element):
        """Extract value from lxml Element or return as-is if already a dict/string"""
        try:
            # If it's already a dict, return it
            if isinstance(element, dict):
                return element

            # If it's an lxml Element, extract its text and tag
            if hasattr(element, 'tag') and hasattr(element, 'text'):
                return {element.tag: element.text}

            # Otherwise return as-is
            return element
        except:
            return element

    def _reconstruct_rows(self, fields, fields_per_row):
        """Reconstruct rows from flat list of field dicts"""
        rows = []
        for i in range(0, len(fields), fields_per_row):
            if i + fields_per_row - 1 < len(fields):
                row = {}
                for field_dict in fields[i:i+fields_per_row]:
                    if isinstance(field_dict, dict):
                        row.update(field_dict)
                if row:
                    rows.append(row)
        return rows


    def list_phone_button_templates(self):
        """
        Get List of Phone Button Templates
        :return: A list of dictionaries with template details
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listPhoneButtonTemplate(
                    {'name': '%'}, returnedTags={
                        'name': '',
                        'isUserModifiable': '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['phoneButtonTemplate']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def get_phone_button_template(self, name):
        """
        Get Phone Button Template details
        :param name: Template name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            resp = self.service.getPhoneButtonTemplate(name=name)
            result['success'] = True
            result['response'] = resp['return']['phoneButtonTemplate']
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def delete_phone_button_template(self, name):
        """
        Delete a Phone Button Template
        :param name: Template name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removePhoneButtonTemplate(name=name)
            result['success'] = True
            result['response'] = f'Phone Button Template "{name}" deleted successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def find_template_references(self, template_name):
        """
        Find all references to a phone button template using SQL query
        :param template_name: Template name
        :return: result dictionary with list of references
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }
        try:
            # Query to find references in device profiles
            query = f"""
            SELECT device.name as device_name, device.pkid
            FROM device
            WHERE device.phonetemplatename = '{template_name}'
            UNION
            SELECT deviceprofile.name as device_name, deviceprofile.pkid
            FROM deviceprofile
            WHERE deviceprofile.phonetemplatename = '{template_name}'
            UNION
            SELECT commonphoneconfig.name as device_name, commonphoneconfig.pkid
            FROM commonphoneconfig
            WHERE commonphoneconfig.phonetemplatename = '{template_name}'
            """

            resp = self.service.executeSQLQuery(sql=query)
            if resp['return'] == None or resp['return'].get('row') is None:
                result['success'] = True
                result['response'] = []
            else:
                rows = resp['return']['row']
                if not isinstance(rows, list):
                    rows = [rows]
                result['success'] = True
                result['response'] = rows
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result


    def list_softkey_templates(self):
        """
        Get List of Softkey Templates with names
        Queries softkeytemplate table to get both UUID and template names
        Excludes system templates that cannot be deleted
        :return: A list of dictionaries with template names and UUIDs
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }

        try:
            # Query softkeytemplate table to get template names and UUIDs
            query = "SELECT pkid, name, description FROM softkeytemplate ORDER BY name"
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                # Reconstruct rows from flat field list
                # Each row has 3 fields (pkid, name, description)
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 3)

                result['success'] = True
                result['response'] = rows
                return serialize_object(result)
        except Fault as error:
            result['error'] = str(error)

        result['success'] = True
        result['response'] = []
        result = serialize_object(result)
        return result


    def get_softkey_template(self, name):
        """
        Get Softkey Template details
        :param name: Template name
        :return: result dictionary with template name
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        column_variants = [
            'softkeytemplate',
            'softkeyTemplate',
            'sk_template',
            'customsoftkeytemplate',
            'softkeyTemplateName'
        ]

        for col in column_variants:
            try:
                query = f"""
                SELECT DISTINCT {col} as name
                FROM device
                WHERE {col} = '{name}'
                LIMIT 1
                """
                resp = self.service.executeSQLQuery(sql=query)
                if resp['return'] != None and resp['return'].get('row') is not None:
                    rows = resp['return']['row']
                    if not isinstance(rows, list):
                        result['response'] = rows
                    else:
                        result['response'] = rows[0] if rows else None
                    result['success'] = True
                    return serialize_object(result)
            except Fault:
                continue

        result['success'] = True
        result['response'] = None
        result = serialize_object(result)
        return result


    def find_softkey_template_dependencies(self, template_name):
        """
        Find all references to a softkey template using SQL query
        Tries multiple possible column names
        :param template_name: Template name or UUID
        :return: result dictionary with list of devices/profiles using this template
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }

        # First, get the template UUID if a name was passed
        template_uuid = template_name
        if not template_name.startswith('{'):  # Check if it looks like a UUID
            get_uuid_query = f"SELECT pkid FROM softkeytemplate WHERE name = '{template_name}'"
            uuid_result = self.execute_sql_query(get_uuid_query)
            if uuid_result.get('success') and uuid_result.get('response'):
                fields = uuid_result.get('response')
                if fields and isinstance(fields[0], dict):
                    template_uuid = fields[0].get('pkid', template_name)

        all_dependencies = []

        # Query device table for phones
        try:
            query = f"""
            SELECT DISTINCT device.name as name, 'Phone' as type
            FROM device
            WHERE device.fksoftkeytemplate = '{template_uuid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                all_dependencies.extend(rows)
        except Fault:
            pass

        # Query commondeviceconfig table
        try:
            query = f"""
            SELECT DISTINCT commondeviceconfig.name as name, 'Common Device Configuration' as type
            FROM commondeviceconfig
            WHERE commondeviceconfig.fksoftkeytemplate = '{template_uuid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                all_dependencies.extend(rows)
        except Fault:
            pass

        # Query deviceprofile table
        try:
            query = f"""
            SELECT DISTINCT deviceprofile.name as name, 'Device Profile' as type
            FROM deviceprofile
            WHERE deviceprofile.fksoftkeytemplate = '{template_uuid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                all_dependencies.extend(rows)
        except Fault:
            pass

        if all_dependencies:
            result['success'] = True
            result['response'] = all_dependencies
            return serialize_object(result)

        # Fallback: try different column name variations
        result['success'] = True
        result['response'] = []
        result = serialize_object(result)
        return result


    def delete_softkey_template(self, name):
        """
        Delete a Softkey Template by name using SQL
        :param name: Template name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            # Delete from softkeytemplate table by name
            query = f"DELETE FROM softkeytemplate WHERE name = '{name}'"
            delete_result = self.execute_sql_update(query)

            if delete_result.get('success'):
                result['success'] = True
                result['response'] = f'Softkey Template "{name}" deleted successfully'
            else:
                result['response'] = 'ERROR'
                result['error'] = delete_result.get('error', 'Failed to delete template')
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        except Exception as error:
            result['response'] = 'ERROR'
            result['error'] = str(error)
        result = serialize_object(result)
        return result


    def _query_location_dependency(self, table_name, type_name, column_name, location_name):
        """
        Helper method to query a table for location dependencies
        :param table_name: Database table name
        :param type_name: Friendly name for the object type
        :param column_name: Column name to search (locationname, location_id, etc)
        :param location_name: Location name to search for
        :return: List of dependency rows
        """
        dependencies = []
        try:
            query = f"""
            SELECT DISTINCT {table_name}.name as name, '{type_name}' as type
            FROM {table_name}
            WHERE {table_name}.{column_name} = '{location_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                dependencies.extend(rows)
        except Fault:
            pass
        return dependencies

    def _query_location_dependency_by_fk(self, table_name, type_name, fk_column, location_name):
        """
        Helper method to query a table using location PKID (foreign key)
        :param table_name: Database table name
        :param type_name: Friendly name for the object type
        :param fk_column: Foreign key column name (e.g., fklocation)
        :param location_name: Location name
        :return: List of dependency rows
        """
        dependencies = []
        try:
            # First, get the PKID of the location
            query = f"SELECT pkid FROM location WHERE name = '{location_name}'"
            location_pk_result = self.execute_sql_query(query)

            if not location_pk_result.get('success') or not location_pk_result.get('response'):
                return dependencies

            # Extract the PKID
            pk_field = location_pk_result.get('response')
            if not pk_field or not isinstance(pk_field[0], dict):
                return dependencies

            location_pkid = pk_field[0].get('pkid')
            if not location_pkid:
                return dependencies

            # Now query the target table using the foreign key
            query = f"""
            SELECT DISTINCT {table_name}.name as name, '{type_name}' as type
            FROM {table_name}
            WHERE {table_name}.{fk_column} = '{location_pkid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                dependencies.extend(rows)
        except Fault:
            pass
        return dependencies

    def find_location_dependencies(self, location_name):
        """
        Find all references to a location using SQL query
        :param location_name: Location name
        :return: result dictionary with list of objects using this location
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }

        all_dependencies = []

        # Try different possible column names for location references
        location_columns = ['locationname', 'locationName', 'location_name']

        # List of tables and their types to check
        tables_to_check = [
            ('devicepool', 'Device Pool'),
            ('device', 'Device'),
            ('deviceprofile', 'Device Profile'),
            ('gatewayendpoint', 'Trunk'),
            ('conferencebridge', 'Conference Bridge'),
            ('mtp', 'Media Termination Point'),
            ('mobilityhub', 'Mobility Hub'),
        ]

        # First, try to find dependencies with location name columns
        for table_name, type_name in tables_to_check:
            for col_name in location_columns:
                deps = self._query_location_dependency(table_name, type_name, col_name, location_name)
                if deps:
                    all_dependencies.extend(deps)
                    break  # Found the right column, move to next table

        # If no dependencies found, try using foreign key with location PKID
        if not all_dependencies:
            fk_columns = ['fklocation', 'location_fk', 'location_pkid']
            for table_name, type_name in tables_to_check:
                for fk_col in fk_columns:
                    deps = self._query_location_dependency_by_fk(table_name, type_name, fk_col, location_name)
                    if deps:
                        all_dependencies.extend(deps)
                        break  # Found the right column, move to next table

        if all_dependencies:
            result['success'] = True
            result['response'] = all_dependencies
            return serialize_object(result)

        result['success'] = True
        result['response'] = []
        result = serialize_object(result)
        return result


    def delete_location(self, name):
        """
        Delete a Location by name
        :param name: Location name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeLocation(name=name)
            result['success'] = True
            result['response'] = f'Location "{name}" deleted successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        except Exception as error:
            result['response'] = 'ERROR'
            result['error'] = str(error)
        result = serialize_object(result)
        return result

    def list_Regions(self):
        """
        Get List of Regions
        :return: A list of dictionaries. If > 1000 records are returned, a list of list of dictionaries will be returned
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            fullResp = self.service.listRegion(
                    {'name' : f'%'}, returnedTags={
                        'name' : '',
                    })
            if fullResp['return'] == None:
                resp = ''
            else:
                resp = fullResp['return']['region']
            result['success'] = True
            result['response'] = resp
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        result = serialize_object(result)
        return result

    def _query_region_dependency(self, table_name, type_name, column_name, region_name):
        """
        Helper method to query a table for region dependencies
        :param table_name: Database table name
        :param type_name: Friendly name for the object type
        :param column_name: Column name to search (regionname, region_id, etc)
        :param region_name: Region name to search for
        :return: List of dependency rows
        """
        dependencies = []
        try:
            query = f"""
            SELECT DISTINCT {table_name}.name as name, '{type_name}' as type
            FROM {table_name}
            WHERE {table_name}.{column_name} = '{region_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                dependencies.extend(rows)
        except Fault:
            pass
        return dependencies

    def _query_region_dependency_by_fk(self, table_name, type_name, fk_column, region_name):
        """
        Helper method to query a table using region PKID (foreign key)
        :param table_name: Database table name
        :param type_name: Friendly name for the object type
        :param fk_column: Foreign key column name (e.g., fkregion)
        :param region_name: Region name
        :return: List of dependency rows
        """
        dependencies = []
        try:
            # First, get the PKID of the region
            query = f"SELECT pkid FROM region WHERE name = '{region_name}'"
            region_pk_result = self.execute_sql_query(query)

            if not region_pk_result.get('success') or not region_pk_result.get('response'):
                return dependencies

            # Extract the PKID
            pk_field = region_pk_result.get('response')
            if not pk_field or not isinstance(pk_field[0], dict):
                return dependencies

            region_pkid = pk_field[0].get('pkid')
            if not region_pkid:
                return dependencies

            # Now query the target table using the foreign key
            query = f"""
            SELECT DISTINCT {table_name}.name as name, '{type_name}' as type
            FROM {table_name}
            WHERE {table_name}.{fk_column} = '{region_pkid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                dependencies.extend(rows)
        except Fault:
            pass
        return dependencies

    def find_region_dependencies(self, region_name):
        """
        Find all references to a region using SQL query
        :param region_name: Region name
        :return: result dictionary with list of objects using this region
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }

        all_dependencies = []

        # Try different possible column names for region references
        region_columns = ['regionname', 'regionName', 'region_name']

        # List of tables and their types to check
        tables_to_check = [
            ('devicepool', 'Device Pool'),
            ('device', 'Device'),
            ('deviceprofile', 'Device Profile'),
            ('gatewayendpoint', 'Trunk'),
            ('conferencebridge', 'Conference Bridge'),
            ('mtp', 'Media Termination Point'),
        ]

        # First, try to find dependencies with region name columns
        for table_name, type_name in tables_to_check:
            for col_name in region_columns:
                deps = self._query_region_dependency(table_name, type_name, col_name, region_name)
                if deps:
                    all_dependencies.extend(deps)
                    break  # Found the right column, move to next table

        # If no dependencies found, try using foreign key with region PKID
        if not all_dependencies:
            fk_columns = ['fkregion', 'region_fk', 'region_pkid']
            for table_name, type_name in tables_to_check:
                for fk_col in fk_columns:
                    deps = self._query_region_dependency_by_fk(table_name, type_name, fk_col, region_name)
                    if deps:
                        all_dependencies.extend(deps)
                        break  # Found the right column, move to next table

        if all_dependencies:
            result['success'] = True
            result['response'] = all_dependencies
            return serialize_object(result)

        result['success'] = True
        result['response'] = []
        result = serialize_object(result)
        return result

    def delete_region(self, name):
        """
        Delete a Region by name
        :param name: Region name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeRegion(name=name)
            result['success'] = True
            result['response'] = f'Region "{name}" deleted successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        except Exception as error:
            result['response'] = 'ERROR'
            result['error'] = str(error)
        result = serialize_object(result)
        return result

    def _query_partition_dependency(self, table_name, type_name, column_name, partition_name):
        """
        Helper method to query a table for partition dependencies
        :param table_name: Database table name
        :param type_name: Friendly name for the object type
        :param column_name: Column name to search (routepartitionname, partition_name, etc)
        :param partition_name: Partition name to search for
        :return: List of dependency rows
        """
        dependencies = []
        try:
            query = f"""
            SELECT DISTINCT {table_name}.name as name, '{type_name}' as type
            FROM {table_name}
            WHERE {table_name}.{column_name} = '{partition_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                dependencies.extend(rows)
        except Fault:
            pass
        return dependencies

    def _query_partition_dependency_by_fk(self, table_name, type_name, fk_column, partition_name):
        """
        Helper method to query a table using partition PKID (foreign key)
        :param table_name: Database table name
        :param type_name: Friendly name for the object type
        :param fk_column: Foreign key column name (e.g., fkroutepartition)
        :param partition_name: Partition name
        :return: List of dependency rows
        """
        dependencies = []
        try:
            # First, get the PKID of the partition
            query = f"SELECT pkid FROM routepartition WHERE name = '{partition_name}'"
            partition_pk_result = self.execute_sql_query(query)

            if not partition_pk_result.get('success') or not partition_pk_result.get('response'):
                return dependencies

            # Extract the PKID
            pk_field = partition_pk_result.get('response')
            if not pk_field or not isinstance(pk_field[0], dict):
                return dependencies

            partition_pkid = pk_field[0].get('pkid')
            if not partition_pkid:
                return dependencies

            # Now query the target table using the foreign key
            query = f"""
            SELECT DISTINCT {table_name}.name as name, '{type_name}' as type
            FROM {table_name}
            WHERE {table_name}.{fk_column} = '{partition_pkid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                dependencies.extend(rows)
        except Fault:
            pass
        return dependencies

    def find_partition_dependencies(self, partition_name):
        """
        Find all references to a partition using SQL query
        :param partition_name: Partition name
        :return: result dictionary with list of objects using this partition
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }

        all_dependencies = []
        debug_info = []

        # First, get the PKID of the partition
        partition_pkid = None
        try:
            query = f"SELECT pkid FROM routepartition WHERE name = '{partition_name}'"
            partition_pk_result = self.execute_sql_query(query)
            debug_info.append(f"get partition pkid: {partition_pk_result}")

            if partition_pk_result.get('success') and partition_pk_result.get('response'):
                pk_field = partition_pk_result.get('response')
                if pk_field and isinstance(pk_field[0], dict):
                    partition_pkid = pk_field[0].get('pkid')
                    debug_info.append(f"Found partition PKID: {partition_pkid}")
        except Fault as e:
            debug_info.append(f"get partition pkid fault: {str(e)}")

        if not partition_pkid:
            result['success'] = True
            result['response'] = []
            result['debug'] = debug_info
            result = serialize_object(result)
            return result

        # Query numplan table for DNs (using FK)
        try:
            query = f"""
            SELECT DISTINCT numplan.dnorpattern as name, 'DN' as type
            FROM numplan
            WHERE numplan.fkroutepartition = '{partition_pkid}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            debug_info.append(f"numplan query: {query_result}")
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                all_dependencies.extend(rows)
        except Fault as e:
            debug_info.append(f"numplan query fault: {str(e)}")

        # Query route patterns (try multiple table names)
        route_pattern_tables = ['dialrule', 'routepattern', 'callroute', 'dialplan']
        for table_name in route_pattern_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Route Pattern' as type
                FROM {table_name}
                WHERE {table_name}.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query translation patterns (try multiple table names)
        tranpattern_tables = ['tranpattern', 'translationpattern', 'translatepattern', 'tranrule']
        for table_name in tranpattern_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Translation Pattern' as type
                FROM {table_name}
                WHERE {table_name}.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query calling search space members (try multiple table names)
        css_tables = ['css', 'callingSearchSpace', 'callingsearchspace', 'csstable']
        for css_table in css_tables:
            try:
                query = f"""
                SELECT DISTINCT {css_table}.name as name, 'Calling Search Space' as type
                FROM {css_table}
                INNER JOIN cssmember ON {css_table}.pkid = cssmember.fkcss
                WHERE cssmember.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{css_table}/cssmember query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{css_table}/cssmember query fault: {str(e)}")

        # Query SIP route patterns
        sip_route_tables = ['siproutepattern', 'sipRoutePattern', 'siproute']
        for table_name in sip_route_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'SIP Route Pattern' as type
                FROM {table_name}
                WHERE {table_name}.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query hunt pilots
        huntpilot_tables = ['huntpilot', 'huntPilot', 'huntroutepilot']
        for table_name in huntpilot_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.name as name, 'Hunt Pilot' as type
                FROM {table_name}
                WHERE {table_name}.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query call pickup groups
        cpg_tables = ['callpickupgroup', 'callPickupGroup', 'cpgroup']
        for table_name in cpg_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Call Pickup Group' as type
                FROM {table_name}
                WHERE {table_name}.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query directed call park
        dcp_tables = ['directedcallpark', 'directedCallPark', 'dcpgroup']
        for table_name in dcp_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.name as name, 'Directed Call Park' as type
                FROM {table_name}
                WHERE {table_name}.fkroutepartition = '{partition_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: {query_result}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    all_dependencies.extend(rows)
                    break  # Found the right table
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        if all_dependencies:
            result['success'] = True
            result['response'] = all_dependencies
            result['debug'] = debug_info
            return serialize_object(result)

        result['success'] = True
        result['response'] = []
        result['debug'] = debug_info
        result = serialize_object(result)
        return result

    def delete_partition(self, name):
        """
        Delete a Partition by name
        :param name: Partition name
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }
        try:
            self.service.removeRoutePartition(name=name)
            result['success'] = True
            result['response'] = f'Partition "{name}" deleted successfully'
        except Fault as error:
            result['response'] = 'ERROR'
            result['error'] = error.message
        except Exception as error:
            result['response'] = 'ERROR'
            result['error'] = str(error)
        result = serialize_object(result)
        return result

    def get_table_info(self, table_name):
        """
        Get sample row from table to inspect column names (for debugging schema)
        :param table_name: Table name to inspect
        :return: result dictionary with sample row data showing column names
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
            'columns': [],
        }
        try:
            query = f"SELECT * FROM {table_name} LIMIT 1"
            query_result = self.execute_sql_query(query)
            if query_result.get('success') and query_result.get('response'):
                # Extract column names from the response
                resp = query_result.get('response')
                if resp and isinstance(resp, list) and len(resp) > 0:
                    if isinstance(resp[0], dict):
                        result['columns'] = list(resp[0].keys())
                    result['response'] = str(resp[0])
                result['success'] = True
            else:
                result['error'] = query_result.get('error', 'No data returned')
        except Exception as e:
            result['error'] = str(e)
        result = serialize_object(result)
        return result

    def _get_device_type(self, product, deviceclass):
        """
        Determine device type from product and class fields
        :param product: Device product field value
        :param deviceclass: Device class field value
        :return: Formatted device type string
        """
        product = (product or '').strip().lower()
        deviceclass = (deviceclass or '').strip().lower()

        # Check for Phone by product name
        if 'ip phone' in product or 'phone' in product:
            return 'Device - Phone'

        # Check for Phone by device class
        if 'phone' in deviceclass:
            return 'Device - Phone'

        # Check for Trunk/Gateway
        if any(x in product for x in ['trunk', 'gateway', 'cube', 'ise']):
            if 'gateway' in product:
                return 'Device - Gateway'
            elif 'trunk' in product:
                return 'Device - Trunk'
            else:
                return 'Device - Trunk'

        # Check for CTI Route Point
        if 'cti' in product or 'cti route point' in product:
            return 'Device - CTI Route Point'

        # Check for Remote Destination Profile
        if 'remote destination' in product or 'rdp' in product:
            return 'Device - Remote Destination Profile'

        # Check for Conference Bridge
        if 'conference' in product or 'bridge' in product:
            return 'Device - Conference Bridge'

        # Check for MTP (Media Termination Point)
        if 'mtp' in product or 'media termination' in product:
            return 'Device - Media Termination Point'

        # Check for IVR
        if 'ivr' in product:
            return 'Device - IVR'

        # Use product as-is if it has a value
        if product and product != 'device':
            return f'Device - {product.title()}'

        # Default
        return 'Device'

    def find_css_dependencies(self, css_name):
        """
        Find all references to a Calling Search Space using SQL query
        :param css_name: CSS name
        :return: result dictionary with list of objects using this CSS
        """
        result = {
            'success': False,
            'response': [],
            'error': '',
        }

        all_dependencies = []
        debug_info = []

        # First, get the PKID of the CSS to use in FK lookups
        css_pkid = None
        try:
            query = f"SELECT pkid FROM callingSearchSpace WHERE name = '{css_name}'"
            query_result = self.execute_sql_query(query)
            success = query_result.get('success')
            error = query_result.get('error', '')
            resp = query_result.get('response')
            debug_info.append(f"CSS PKID lookup: success={success}, resp_count={len(resp) if resp else 0}, error={error[:50] if error else ''}")
            if success and resp:
                if isinstance(resp[0], dict):
                    css_pkid = resp[0].get('pkid')
                    debug_info.append(f"  -> Found CSS PKID: {css_pkid}")
        except Fault as e:
            debug_info.append(f"CSS PKID lookup fault: {str(e)}")

        if not css_pkid:
            result['success'] = True
            result['response'] = []
            result['debug'] = debug_info
            result = serialize_object(result)
            return result

        # CSS foreign key columns found in device table
        device_css_fk_columns = [
            'fkcallingsearchspace',
            'fkcallingsearchspace_callednational',
            'fkcallingsearchspace_cgpningressdn',
            'fkcallingsearchspace_rdntransform',
            'fkcallingsearchspace_restrict',
            'fkcallingsearchspace_cdpntransform',
            'fkcallingsearchspace_cgpnintl',
            'fkcallingsearchspace_cgpnnational',
            'fkcallingsearchspace_calledunknown',
            'fkcallingsearchspace_cgpnsubscriber',
            'fkcallingsearchspace_cgpnunknown',
            'fkcallingsearchspace_cgpntransform',
            'fkcallingsearchspace_calledsubscriber',
            'fkcallingsearchspace_refer',
            'fkcallingsearchspace_reroute',
            'fkcallingsearchspace_aar',
            'fkcallingsearchspace_calledintl',
        ]

        # Query devices with this CSS via FK (try to include product for better descriptions)
        for fk_col in device_css_fk_columns:
            try:
                # Try to fetch with product field for better descriptions
                query = f"""
                SELECT DISTINCT device.name as name, COALESCE(device.product, '') as product, COALESCE(device.class, '') as deviceclass
                FROM device
                WHERE device.{fk_col} = '{css_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                success = query_result.get('success')
                error = query_result.get('error', '')
                resp = query_result.get('response', [])
                debug_info.append(f"device {fk_col}: success={success}, resp_count={len(resp) if resp else 0}, error={error[:50] if error else ''}")

                # If product query failed, try simple name query
                if not success or not resp:
                    query = f"""
                    SELECT DISTINCT device.name as name, 'Device' as product, '' as deviceclass
                    FROM device
                    WHERE device.{fk_col} = '{css_pkid}'
                    ORDER BY name
                    """
                    query_result = self.execute_sql_query(query)
                    success = query_result.get('success')
                    resp = query_result.get('response', [])

                if success and resp:
                    fields = resp
                    rows = self._reconstruct_rows(fields, 3)
                    if rows:
                        for row in rows:
                            product = row.get('product', '').strip() if isinstance(row.get('product'), str) else ''
                            deviceclass = row.get('deviceclass', '').strip() if isinstance(row.get('deviceclass'), str) else ''

                            # Determine device type
                            device_type = self._get_device_type(product, deviceclass)
                            row['type'] = device_type
                        all_dependencies.extend(rows)
                        debug_info.append(f"  -> Found {len(rows)} devices")
            except Fault as e:
                debug_info.append(f"device {fk_col}: fault={str(e)[:50]}")


        # CSS foreign key columns found in numplan table
        numplan_css_fk_columns = [
            'fkcallingsearchspace_cfhrint',
            'fkcallingsearchspace_mwi',
            'fkcallingsearchspace_cfnaint',
            'fkcallingsearchspace_translation',
            'fkcallingsearchspace_revert',
            'fkcallingsearchspace_cfurint',
            'fkcallingsearchspace_pkmonfwdnoretint',
            'fkcallingsearchspace_cfhr',
            'fkcallingsearchspace_cfbint',
            'fkcallingsearchspace_cfapt',
            'fkcallingsearchspace_sharedlineappear',
            'fkcallingsearchspace_pkmonfwdnoret',
            'fkcallingsearchspace_cfb',
            'fkcallingsearchspace_pff',
            'fkcallingsearchspace_cfna',
            'fkcallingsearchspace_devicefailure',
            'fkcallingsearchspace_pffint',
            'fkcallingsearchspace_reroute',
            'fkcallingsearchspace_cfur',
        ]

        # CSS column name variants for gateway/trunk/common device config tables
        css_col_variants = [
            'callingSearchSpaceName',
            'callingSearchSpace',
            'cssName',
            'callingSearchSpaceId',
            'css_name',
        ]

        # Query DNs (numplan) with this CSS via FK
        for fk_col in numplan_css_fk_columns:
            try:
                query = f"""
                SELECT DISTINCT numplan.dnorpattern as name, 'DN' as type
                FROM numplan
                WHERE numplan.{fk_col} = '{css_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                success = query_result.get('success')
                error = query_result.get('error', '')
                resp = query_result.get('response', [])
                if resp:  # Only log if there's a response
                    debug_info.append(f"numplan {fk_col}: success={success}, resp_count={len(resp)}")
                if success and resp:
                    fields = resp
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        debug_info.append(f"  -> Found {len(rows)} DNs")
            except Fault as e:
                debug_info.append(f"numplan {fk_col}: fault={str(e)[:50]}")

        # Query Device Pools with this CSS (via FK)
        devicepool_css_fk_columns = [
            'fkcallingsearchspace',
            'fkcallingsearchspace_mobility',
        ]
        for fk_col in devicepool_css_fk_columns:
            try:
                query = f"""
                SELECT DISTINCT devicepool.name as name, 'Device Pool' as type
                FROM devicepool
                WHERE devicepool.{fk_col} = '{css_pkid}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                success = query_result.get('success')
                error = query_result.get('error', '')
                resp = query_result.get('response', [])
                if resp:
                    debug_info.append(f"devicepool {fk_col}: success={success}, resp_count={len(resp)}")
                if success and resp:
                    fields = resp
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        debug_info.append(f"  -> Found {len(rows)} device pools with {fk_col}")
            except Fault as e:
                debug_info.append(f"devicepool {fk_col}: fault={str(e)[:50]}")

        # Query gateway endpoints (trunks) with this CSS
        gateway_tables = ['gatewayendpoint', 'trunk', 'gateway', 'gatewaytrunk', 'endpoint']
        for table_name in gateway_tables:
            for col_name in css_col_variants:
                try:
                    query = f"""
                    SELECT DISTINCT {table_name}.name as name, 'Trunk' as type
                    FROM {table_name}
                    WHERE {table_name}.{col_name} = '{css_name}'
                    ORDER BY name
                    """
                    query_result = self.execute_sql_query(query)
                    success = query_result.get('success')
                    error = query_result.get('error', '')
                    resp = query_result.get('response', [])
                    if success and resp:
                        fields = resp
                        rows = self._reconstruct_rows(fields, 2)
                        if rows:
                            all_dependencies.extend(rows)
                            debug_info.append(f"Found {len(rows)} trunks in {table_name} with {col_name}")
                            break
                except Fault as e:
                    pass

        # Query common device config
        for col_name in css_col_variants:
            try:
                query = f"""
                SELECT DISTINCT commondeviceconfig.name as name, 'Common Device Config' as type
                FROM commondeviceconfig
                WHERE commondeviceconfig.{col_name} = '{css_name}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                success = query_result.get('success')
                error = query_result.get('error', '')
                resp = query_result.get('response', [])
                debug_info.append(f"commondeviceconfig query (col={col_name}): success={success}, error={error}")
                if success and resp:
                    fields = resp
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        debug_info.append(f"  Found {len(rows)} common device configs with {col_name}")
                        break
            except Fault as e:
                debug_info.append(f"commondeviceconfig query fault (col={col_name}): {str(e)}")

        # Query IVR portals
        try:
            query = f"""
            SELECT DISTINCT ivrportal.name as name, 'IVR Portal' as type
            FROM ivrportal
            WHERE ivrportal.callingSearchSpaceName = '{css_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            debug_info.append(f"ivrportal query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                if rows:
                    all_dependencies.extend(rows)
        except Fault as e:
            debug_info.append(f"ivrportal query fault: {str(e)}")

        # Query route patterns
        route_pattern_tables = ['routepattern', 'dialrule', 'callroute']
        for table_name in route_pattern_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Route Pattern' as type
                FROM {table_name}
                WHERE {table_name}.callingSearchSpaceName = '{css_name}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        break
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query translation patterns
        tranpattern_tables = ['tranpattern', 'translationpattern', 'translatepattern']
        for table_name in tranpattern_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Translation Pattern' as type
                FROM {table_name}
                WHERE {table_name}.callingSearchSpaceName = '{css_name}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        break
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query hunt pilots
        huntpilot_tables = ['huntpilot', 'huntPilot', 'huntroutepilot']
        for table_name in huntpilot_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Hunt Pilot' as type
                FROM {table_name}
                WHERE {table_name}.callingSearchSpaceName = '{css_name}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        break
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query call pickup groups
        cpg_tables = ['callpickupgroup', 'callPickupGroup', 'cpgroup']
        for table_name in cpg_tables:
            try:
                query = f"""
                SELECT DISTINCT {table_name}.pattern as name, 'Call Pickup Group' as type
                FROM {table_name}
                WHERE {table_name}.callingSearchSpaceName = '{css_name}'
                ORDER BY name
                """
                query_result = self.execute_sql_query(query)
                debug_info.append(f"{table_name} query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
                if query_result.get('success') and query_result.get('response'):
                    fields = query_result.get('response')
                    rows = self._reconstruct_rows(fields, 2)
                    if rows:
                        all_dependencies.extend(rows)
                        break
            except Fault as e:
                debug_info.append(f"{table_name} query fault: {str(e)}")

        # Query voice mail profiles
        try:
            query = f"""
            SELECT DISTINCT voicemailprofile.name as name, 'Voice Mail Profile' as type
            FROM voicemailprofile
            WHERE voicemailprofile.callingSearchSpaceName = '{css_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            debug_info.append(f"voicemailprofile query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                if rows:
                    all_dependencies.extend(rows)
        except Fault as e:
            debug_info.append(f"voicemailprofile query fault: {str(e)}")

        # Query conference bridges
        try:
            query = f"""
            SELECT DISTINCT conferencebridge.name as name, 'Conference Bridge' as type
            FROM conferencebridge
            WHERE conferencebridge.callingSearchSpaceName = '{css_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            debug_info.append(f"conferencebridge query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                if rows:
                    all_dependencies.extend(rows)
        except Fault as e:
            debug_info.append(f"conferencebridge query fault: {str(e)}")

        # Query MTP (Media Termination Points)
        try:
            query = f"""
            SELECT DISTINCT mtp.name as name, 'Media Termination Point' as type
            FROM mtp
            WHERE mtp.callingSearchSpaceName = '{css_name}'
            ORDER BY name
            """
            query_result = self.execute_sql_query(query)
            debug_info.append(f"mtp query: success={query_result.get('success')}, resp_len={len(query_result.get('response', []))}")
            if query_result.get('success') and query_result.get('response'):
                fields = query_result.get('response')
                rows = self._reconstruct_rows(fields, 2)
                if rows:
                    all_dependencies.extend(rows)
        except Fault as e:
            debug_info.append(f"mtp query fault: {str(e)}")

        if all_dependencies:
            result['success'] = True
            result['response'] = all_dependencies
            result['debug'] = debug_info
            return serialize_object(result)

        result['success'] = True
        result['response'] = []
        result['debug'] = debug_info
        result = serialize_object(result)
        return result
            