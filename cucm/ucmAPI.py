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


    def add_Region(self, region):
        """
        Add a region
        :param region: Name of the region to add
        :return: result dictionary
        """
        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        request = {'name': region}

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
            result['error'] = error.message
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
            result['error'] = error.message
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
        

        result = {
            'success': False,
            'response': '',
            'error': '',
        }

        if resp['return'] == None:
            result['response'] = 'Error'
            result['error'] = resp
            result = serialize_object(result)
            return result
        else:
            result['success'] = True
            result['response'] = resp
            result = serialize_object(result)
            return result
            