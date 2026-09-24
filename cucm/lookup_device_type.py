#!/usr/bin/env python3

"""
Look up CUCM device type

Queries CUCM to identify what type of device a name represents.
Supports: IP Phone, Analog Device, CTI Port, CTI Route Point, Device Profile, Trunk, Remote Destination Profile, Route Pattern, Translation Pattern

Usage:
  python3 cucm/lookup_device_type.py
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from setup.multi_object_loader import get_object_for_single_operation, load_credentials
from setup.logger import setup_logger
from cucm.ucmAPI import AXL
from zeep.exceptions import Fault

def get_device_type_from_phone_data(phone_data):
    """
    Determine device type from phone object data
    :param phone_data: Phone object from getPhone() response
    :return: Device type string
    """
    if not phone_data:
        return None

    product = (phone_data.get('product') or '').strip()
    device_class = (phone_data.get('class') or '').strip()

    product_lower = product.lower()
    class_lower = device_class.lower()

    if 'cti port' in product_lower:
        return 'CTI Port'

    if 'remote destination' in product_lower or 'rdp' in product_lower:
        return 'Remote Destination Profile'

    if 'conference' in product_lower:
        return 'Conference Bridge'

    if 'mtp' in product_lower:
        return 'Media Termination Point'

    if 'phone' in product_lower or 'phone' in class_lower:
        return 'IP Phone'

    if product:
        return product

    return None

def lookup_device_type(cluster, device_name, basepath, logger, axl_connection=None):
    """
    Look up device type in CUCM
    :param cluster: Cluster object with server, username, password, version
    :param device_name: Device name to look up
    :param basepath: Base path to schema directory
    :param logger: Logger instance
    :param axl_connection: Optional existing AXL connection (if provided, cluster credentials are not needed)
    :return: Device type string or None if not found
    """
    logger.debug(f"Looking up device: {device_name}")

    if axl_connection:
        axl = axl_connection
    else:
        wsdl_file = str((basepath / 'schema' / cluster['version'] / 'AXLAPI.wsdl').absolute())

        try:
            axl = AXL(
                username=cluster['username'],
                password=cluster['password'],
                wsdl=wsdl_file,
                cucm=cluster['server'],
                cucm_version=cluster['version']
            )
        except Exception as e:
            logger.error(f"Failed to connect to CUCM: {e}")
            return None

    try:
        logger.debug(f"Trying getAnalogDevice() for {device_name}")
        resp = axl.service.getAnalogDevice(name=device_name)
        logger.debug(f"Found as Analog Device")
        return 'Analog Device'
    except Fault as e:
        logger.debug(f"getAnalogDevice() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getAnalogDevice() error: {e}")

    try:
        logger.debug(f"Trying getCtiRoutePoint() for {device_name}")
        resp = axl.service.getCtiRoutePoint(name=device_name)
        logger.debug(f"Found as CTI Route Point")
        return 'CTI Route Point'
    except Fault as e:
        logger.debug(f"getCtiRoutePoint() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getCtiRoutePoint() error: {e}")

    try:
        logger.debug(f"Trying getPhone() for {device_name}")
        resp = axl.get_Phone(name=device_name)  # type: ignore

        if resp.get('success') and resp.get('response'):
            device_type = get_device_type_from_phone_data(resp.get('response'))
            if device_type:
                logger.debug(f"Found as Phone type: {device_type}")
                return device_type
    except Fault as e:
        logger.debug(f"getPhone() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getPhone() error: {e}")

    try:
        logger.debug(f"Trying getDeviceProfile() for {device_name}")
        resp = axl.service.getDeviceProfile(name=device_name)
        logger.debug(f"Found as Device Profile")
        return 'Device Profile'
    except Fault as e:
        logger.debug(f"getDeviceProfile() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getDeviceProfile() error: {e}")

    try:
        logger.debug(f"Trying getTrunk() for {device_name}")
        resp = axl.service.getTrunk(name=device_name)
        logger.debug(f"Found as Trunk")
        return 'Trunk'
    except Fault as e:
        logger.debug(f"getTrunk() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getTrunk() error: {e}")

    try:
        logger.debug(f"Trying getRemoteDestinationProfile() for {device_name}")
        resp = axl.service.getRemoteDestinationProfile(name=device_name)
        logger.debug(f"Found as Remote Destination Profile")
        return 'Remote Destination Profile'
    except Fault as e:
        logger.debug(f"getRemoteDestinationProfile() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getRemoteDestinationProfile() error: {e}")

    try:
        logger.debug(f"Trying getRoutePattern() for {device_name}")
        resp = axl.service.getRoutePattern(pattern=device_name)
        logger.debug(f"Found as Route Pattern")
        return 'Route Pattern'
    except Fault as e:
        logger.debug(f"getRoutePattern() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getRoutePattern() error: {e}")

    try:
        logger.debug(f"Trying getTranslationPattern() for {device_name}")
        resp = axl.service.getTranslationPattern(pattern=device_name)
        logger.debug(f"Found as Translation Pattern")
        return 'Translation Pattern'
    except Fault as e:
        logger.debug(f"getTranslationPattern() failed: {str(e)[:100]}")
    except Exception as e:
        logger.debug(f"getTranslationPattern() error: {e}")

    try:
        logger.debug(f"Trying SQL query for {device_name}")
        escaped_name = device_name.replace("'", "''")
        query = f"""
        SELECT device.product, device.class
        FROM device
        WHERE device.name = '{escaped_name}'
        LIMIT 1
        """
        resp = axl.execute_sql_query(query)

        if resp['success'] and resp['response']:
            row = resp['response'][0] if isinstance(resp['response'], list) else resp['response']
            if isinstance(row, dict):
                device_type = get_device_type_from_phone_data(row)
                if device_type:
                    logger.debug(f"Found via SQL query as: {device_type}")
                    return device_type
    except Exception as e:
        logger.debug(f"SQL query failed: {e}")

    try:
        logger.debug(f"Trying SQL query for Route Pattern: {device_name}")
        escaped_name = device_name.replace("'", "''")
        query = f"""
        SELECT 'Route Pattern' as type
        FROM routeplan
        WHERE pattern = '{escaped_name}'
        LIMIT 1
        """
        resp = axl.execute_sql_query(query)

        if resp['success'] and resp['response']:
            logger.debug(f"Found as Route Pattern via SQL")
            return 'Route Pattern'
    except Exception as e:
        logger.debug(f"Route Pattern SQL query failed: {e}")

    try:
        logger.debug(f"Trying SQL query for Translation Pattern: {device_name}")
        escaped_name = device_name.replace("'", "''")
        query = f"""
        SELECT 'Translation Pattern' as type
        FROM translationpattern
        WHERE pattern = '{escaped_name}'
        LIMIT 1
        """
        resp = axl.execute_sql_query(query)

        if resp['success'] and resp['response']:
            logger.debug(f"Found as Translation Pattern via SQL")
            return 'Translation Pattern'
    except Exception as e:
        logger.debug(f"Translation Pattern SQL query failed: {e}")

    try:
        logger.debug(f"Trying wildcard SQL query for patterns matching: {device_name}")
        escaped_name = device_name.replace("'", "''")
        query = f"""
        SELECT 'Route Pattern' as type
        FROM routeplan
        WHERE pattern LIKE '%{escaped_name}%'
        LIMIT 1
        """
        resp = axl.execute_sql_query(query)

        if resp['success'] and resp['response']:
            logger.debug(f"Found as Route Pattern via wildcard SQL")
            return 'Route Pattern'
    except Exception as e:
        logger.debug(f"Route Pattern wildcard SQL query failed: {e}")

    try:
        logger.debug(f"Trying wildcard SQL query for translation patterns matching: {device_name}")
        escaped_name = device_name.replace("'", "''")
        query = f"""
        SELECT 'Translation Pattern' as type
        FROM translationpattern
        WHERE pattern LIKE '%{escaped_name}%'
        LIMIT 1
        """
        resp = axl.execute_sql_query(query)

        if resp['success'] and resp['response']:
            logger.debug(f"Found as Translation Pattern via wildcard SQL")
            return 'Translation Pattern'
    except Exception as e:
        logger.debug(f"Translation Pattern wildcard SQL query failed: {e}")

    logger.warning(f"Device '{device_name}' not found in CUCM")
    return None

def main():
    basepath = Path(__file__).parent
    logger = setup_logger('./cucm/lookup_device_type.py', './logs')

    logger.info("=" * 60)
    logger.info("CUCM Device Type Lookup")
    logger.info("=" * 60)

    cluster = get_object_for_single_operation(
        basepath=basepath,
        service='CUCM'
    )

    if not cluster:
        logger.error("No cluster selected")
        return

    logger.info(f"Using cluster: {cluster['name']}")

    username, password = load_credentials(
        service='CUCM',
        object_name=cluster['name']
    )

    if not username or not password:
        logger.error("Failed to load credentials")
        return

    cluster['username'] = username
    cluster['password'] = password

    device_name = input("\nEnter device name to lookup: ").strip()

    if not device_name:
        logger.error("Device name cannot be empty")
        return

    device_type = lookup_device_type(cluster, device_name, basepath, logger)

    print("\n" + "=" * 60)
    if device_type:
        print(f"Device: {device_name}")
        print(f"Type: {device_type}")
        logger.info(f"Lookup successful: {device_name} = {device_type}")
    else:
        print(f"Device '{device_name}' not found")
        logger.warning(f"Device not found: {device_name}")
    print("=" * 60)

if __name__ == '__main__':
    main()
