#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Clean up unused phone button templates matching a search text

This script identifies and optionally deletes phone button templates that:
1. Have names containing a user-specified text (e.g., 'SEP', 'TEST', etc.)
2. Are not assigned to any phones in the system

Results are displayed on screen and logged to file.

Usage:
  python3 clean_unused_phone_button_templates.py               (list & prompt to delete)
  python3 clean_unused_phone_button_templates.py -d            (delete with confirmation for each)
  python3 clean_unused_phone_button_templates.py -D            (delete all without confirmation)
  python3 clean_unused_phone_button_templates.py --default     (same as -D)

Default behavior (no flags):
  - Prompts for search text (e.g., 'SEP', 'TEST', 'CUSTOM', etc.)
  - Lists all unused templates containing that text anywhere in the name
  - Prompts user: "Delete these X unused template(s)?"
  - If yes: deletes with confirmation for each template
  - If no: exits without deletion
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from datetime import datetime
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_object_for_single_operation, load_credentials, get_objects_for_multi_operation, load_credentials_for_multi_objects
from ucmAPI import AXL


def find_unused_templates(axl, logger, search_text='SEP'):
    """Find phone button templates containing search_text that are not in use
    :param axl: AXL client
    :param logger: Logger instance
    :param search_text: Text to search for anywhere in template name (default: 'SEP')
    :return: Tuple of (all_matching_templates, unused_templates)
    """
    logger.info('Retrieving all phone button templates...')

    # Get all templates
    templates_result = axl.list_phone_button_templates()
    if not templates_result.get('success'):
        logger.error('Failed to retrieve phone button templates: %s', templates_result.get('error'))
        return [], []

    templates = templates_result.get('response')
    if not templates:
        logger.warning('No phone button templates found')
        return [], []

    # Ensure templates is a list
    if not isinstance(templates, list):
        templates = [templates]

    logger.info('Found %d total phone button templates', len(templates))

    # Filter templates containing the search text and that are user-modifiable
    matching_templates = []
    for t in templates:
        if isinstance(t, dict):
            name = t.get('name')
            is_user_modifiable = t.get('isUserModifiable')
            if name and search_text in name:
                # Check if template is user-modifiable (handle both boolean and string representations)
                is_modifiable = is_user_modifiable and str(is_user_modifiable).lower() != 'false'
                if is_modifiable:
                    matching_templates.append(name)
                    logger.debug('Template %s is user-modifiable', name)
                else:
                    logger.debug('Skipping template %s (not user-modifiable, isUserModifiable=%s)', name, is_user_modifiable)

    matching_templates = sorted(list(set(matching_templates)))
    logger.info('Found %d user-modifiable templates containing %s', len(matching_templates), search_text)

    if not matching_templates:
        logger.info('No templates containing %s found', search_text)
        return [], []

    # Collect all template names in use
    templates_in_use = set()

    # Check phones for direct template usage
    logger.info('Checking phones for direct template usage...')
    phones_result = axl.list_Phone()
    if phones_result.get('success'):
        phones = phones_result.get('response')
        if not isinstance(phones, list):
            phones = [phones] if phones else []

        for phone in phones:
            if isinstance(phone, dict):
                template_name = phone.get('phoneTemplateName')
                if template_name:
                    # Handle case where template_name might be an OrderedDict or dict
                    if isinstance(template_name, dict):
                        # Extract the actual value from dict
                        template_name = str(list(template_name.values())[0]) if template_name else None
                    else:
                        template_name = str(template_name)

                    if template_name and template_name != 'None':
                        templates_in_use.add(template_name)
                        logger.debug('Phone %s uses template %s', phone.get('name'), template_name)
    else:
        logger.warning('Could not retrieve phones: %s', phones_result.get('error'))

    # Check device profiles for template usage
    logger.info('Checking device profiles for template usage...')
    query = "SELECT phonetemplatename FROM deviceprofile WHERE phonetemplatename IS NOT NULL"
    dp_result = axl.execute_sql_query(query)
    if dp_result.get('success'):
        rows = dp_result.get('response', [])
        for row in rows:
            if isinstance(row, dict):
                template_name = row.get('phonetemplatename')
                if template_name:
                    # Handle case where template_name might be an OrderedDict or dict
                    if isinstance(template_name, dict):
                        template_name = str(list(template_name.values())[0]) if template_name else None
                    else:
                        template_name = str(template_name)

                    if template_name and template_name != 'None':
                        templates_in_use.add(template_name)
                        logger.debug('Device profile uses template %s', template_name)
    else:
        logger.warning('Could not query device profiles: %s', dp_result.get('error'))

    # Check common phone configs for template usage
    logger.info('Checking common phone configurations for template usage...')
    query = "SELECT phonetemplatename FROM commonphoneconfig WHERE phonetemplatename IS NOT NULL"
    cpc_result = axl.execute_sql_query(query)
    if cpc_result.get('success'):
        rows = cpc_result.get('response', [])
        for row in rows:
            if isinstance(row, dict):
                template_name = row.get('phonetemplatename')
                if template_name:
                    # Handle case where template_name might be an OrderedDict or dict
                    if isinstance(template_name, dict):
                        template_name = str(list(template_name.values())[0]) if template_name else None
                    else:
                        template_name = str(template_name)

                    if template_name and template_name != 'None':
                        templates_in_use.add(template_name)
                        logger.debug('Common phone config uses template %s', template_name)
    else:
        logger.warning('Could not query common phone configs: %s', cpc_result.get('error'))

    logger.info('%d unique templates are in use', len(templates_in_use))

    # Find unused templates matching the prefix
    unused_templates = []
    for template_name in matching_templates:
        if template_name not in templates_in_use:
            unused_templates.append(template_name)
            logger.info('Found unused template: %s', template_name)

    return matching_templates, sorted(unused_templates)


def display_results(axl, all_matching_templates, unused_templates, logger, search_text='SEP'):
    """Display results in a formatted way showing both unused and in-use templates
    :param axl: AXL client
    :param all_matching_templates: All templates matching the search text
    :param unused_templates: List of unused templates
    :param logger: Logger instance
    :param search_text: Text being searched for
    """

    # Determine which templates are in use
    in_use_templates = [t for t in all_matching_templates if t not in unused_templates]

    # Display unused templates
    print('\n' + '=' * 70)
    print(f'UNUSED PHONE BUTTON TEMPLATES (Containing {search_text})')
    print('=' * 70)

    if not unused_templates:
        print('\nNo unused templates found.')
        logger.info('No unused templates found')
    else:
        print(f'\nFound {len(unused_templates)} unused template(s):\n')
        for idx, template in enumerate(unused_templates, 1):
            print(f'  {idx}. {template}')
            logger.info('Unused template: %s', template)

    # Display in-use templates
    print('\n' + '=' * 70)
    print(f'IN-USE PHONE BUTTON TEMPLATES (Containing {search_text})')
    print('=' * 70)

    if not in_use_templates:
        print(f'\nNo templates containing {search_text} are currently in use.')
        logger.info('No templates containing %s are in use', search_text)
    else:
        print(f'\nFound {len(in_use_templates)} in-use template(s):\n')
        for idx, template in enumerate(in_use_templates, 1):
            print(f'  {idx}. {template}')
            logger.info('In-use template: %s', template)

    print('=' * 70)
    print(f'\nSummary: {len(in_use_templates)} in-use, {len(unused_templates)} unused')
    print('=' * 70 + '\n')

    return len(unused_templates) == 0


def prompt_for_search_text():
    """Prompt user for the search text to use when finding templates
    :return: Search text string (default: 'SEP')
    """
    text = input('Enter text to search for in template names (default: SEP): ').strip()
    if not text:
        text = 'SEP'
    return text


def prompt_for_deletion(unused_templates, logger):
    """Prompt user if they want to delete the unused templates
    :param unused_templates: List of template names
    :param logger: Logger instance
    :return: True if user wants to delete, False otherwise
    """
    confirmed = prompt_yes_no(f'\nDelete these {len(unused_templates)} unused template(s)?', default=False)
    if confirmed:
        logger.info('User confirmed deletion of %d templates', len(unused_templates))
        return True
    else:
        logger.info('User declined to delete templates')
        return False


def find_template_references(axl, template_name, logger):
    """Find what is referencing a template
    :param axl: AXL client
    :param template_name: Template name to check
    :param logger: Logger instance
    :return: List of references or empty list if none found
    """
    result = axl.find_template_references(template_name)
    if result.get('success'):
        return result.get('response', [])
    return []


def delete_templates(axl, unused_templates, logger, auto_delete=False, confirm=True, skip_initial_prompt=False):
    """Delete unused templates with optional confirmation
    :param axl: AXL client
    :param unused_templates: List of template names to delete
    :param logger: Logger instance
    :param auto_delete: If True, delete without confirmation
    :param confirm: If True and auto_delete is False, ask for confirmation
    :param skip_initial_prompt: If True, skip the initial deletion prompt (already asked)
    :return: Number of successfully deleted templates
    """
    if not unused_templates:
        return 0

    if not auto_delete and confirm and not skip_initial_prompt:
        if not prompt_for_deletion(unused_templates, logger):
            return 0

    deleted_count = 0
    failed_templates = []

    for template in unused_templates:
        # Check for references before attempting delete
        references = find_template_references(axl, template, logger)

        if references:
            logger.warning('Template %s is still in use by: %s', template, references)
            ref_list = ', '.join([ref.get('device_name', 'Unknown') for ref in references if isinstance(ref, dict)])
            print(f'  ✗ Cannot delete {template}')
            print(f'    Still in use by: {ref_list}')
            failed_templates.append(template)
            continue

        result = axl.delete_phone_button_template(template)
        if result.get('success'):
            logger.info('Deleted template: %s', template)
            print(f'  ✓ Deleted: {template}')
            deleted_count += 1
        else:
            logger.error('Failed to delete template %s: %s', template, result.get('error'))
            error_msg = result.get('error', 'Unknown error')
            print(f'  ✗ Failed to delete {template}')
            print(f'    Error: {error_msg}')
            failed_templates.append(template)

    if failed_templates:
        print(f"\n{'=' * 70}")
        print(f'Could not delete {len(failed_templates)} template(s) (still in use):')
        for template in failed_templates:
            print(f'  - {template}')
        print(f"{'=' * 70}")
        logger.info('Failed to delete %d templates', len(failed_templates))

    return deleted_count


def run_operation_on_cluster(basepath, cluster_data, logger, search_text='SEP', auto_delete=False, confirm=True):
    """Run the find and optional delete operation on a single cluster
    :param basepath: Base path for schema files
    :param cluster_data: Cluster configuration dict
    :param logger: Logger instance
    :param search_text: Text to search for in template names
    :param auto_delete: If True, delete without confirmation
    :param confirm: If True, ask for confirmation before deletion
    """
    cluster_name = cluster_data.get('name', 'unknown')
    server = cluster_data.get('server', 'unknown')
    try:
        cluster_name = cluster_data['name']
        server = cluster_data['server']
        version = cluster_data['version']

        username, password = load_credentials('CUCM', cluster_name)

        # Setup AXL Connection to CUCM
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        logger.info('=' * 60)
        logger.info('Processing cluster: %s (%s)', cluster_name, server)
        logger.info('=' * 60)

        all_matching_templates, unused_templates = find_unused_templates(axl, logger, search_text=search_text)
        is_empty = display_results(axl, all_matching_templates, unused_templates, logger, search_text=search_text)

        if not is_empty:
            if confirm or auto_delete:
                deleted_count = delete_templates(axl, unused_templates, logger, auto_delete=auto_delete, confirm=confirm)
            else:
                if prompt_for_deletion(unused_templates, logger):
                    deleted_count = delete_templates(axl, unused_templates, logger, auto_delete=False, confirm=True, skip_initial_prompt=True)
                else:
                    deleted_count = 0

            if deleted_count > 0:
                print(f"\n{'=' * 70}")
                print(f'Successfully deleted {deleted_count} template(s)')
                print(f"{'=' * 70}\n")
                logger.info('Deleted %d templates', deleted_count)

        logger.info('Completed cluster: %s', cluster_name)
        print(f"✓ Completed {cluster_name} ({server})")
        return True
    except Exception as e:
        logger.error('Error processing cluster %s: %s', cluster_name, str(e))
        print(f"✗ Failed on {cluster_name}: {str(e)}")
        return False


def run_on_all_clusters(basepath, clusters_data, logger, search_text='SEP', auto_delete=False, confirm=True):
    """Run operation on all clusters sequentially
    :param basepath: Base path for schema files
    :param clusters_data: List of cluster configurations
    :param logger: Logger instance
    :param search_text: Text to search for in template names
    :param auto_delete: If True, delete without confirmation
    :param confirm: If True, ask for confirmation before deletion
    """
    print(f"\nProcessing {len(clusters_data)} clusters...\n")

    # Load credentials using the new loader
    print("="*80)
    print("Loading Credentials")
    print("="*80)
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)

    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_data, use_same=use_same)

    successful = 0
    failed = 0

    for cluster in clusters_data:
        if run_operation_on_cluster(basepath, cluster, logger, search_text=search_text, auto_delete=auto_delete, confirm=confirm):
            successful += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Completed: {successful} successful, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean up unused phone button templates starting with SEP')
    parser.add_argument('-d', action='store_true', help='Delete unused templates with confirmation')
    parser.add_argument('-D', action='store_true', help='Delete unused templates without confirmation')
    parser.add_argument('--default', action='store_true', help='Same as -D (delete without confirmation)')
    args = parser.parse_args()

    auto_delete = args.D or args.default
    confirm = args.d and not (args.D or args.default)
    should_delete = args.d or args.D or args.default

    basepath = Path.cwd()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"../_logs/{timestamp}-clean-unused-phone-button-templates.log"
    logger = setup_logger(log_file)
    logger.info("Clean Unused Phone Button Templates - Started")
    if should_delete:
        if auto_delete:
            logger.info("Mode: Auto-delete without confirmation")
        else:
            logger.info("Mode: Delete with confirmation prompt")
    else:
        logger.info("Mode: List only (no deletion)")

    # Prompt for search text
    search_text = prompt_for_search_text()
    logger.info("Search text: %s", search_text)

    use_multiple = False

    clusters_data = get_objects_for_multi_operation(basepath, 'CUCM', server_type='publisher')
    if clusters_data:
        use_multiple = prompt_yes_no(f'{len(clusters_data)} clusters found. Use multiple clusters?', default=False)

        if use_multiple:
            if not clusters_data:
                print("No clusters found in clusters.csv")
                exit(1)

            run_on_all_clusters(basepath, clusters_data, logger, search_text=search_text, auto_delete=auto_delete, confirm=confirm)
        else:
            # Single cluster mode - user said 'n' to multiple clusters
            cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
            if not cluster:
                print("Error: Unable to load cluster information")
                sys.exit(1)

            username, password = load_credentials('CUCM', cluster['name'])

            server = cluster['server']
            version = cluster['version']

            wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
            wsdl = wsdl_dir.absolute().as_uri()
            axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

            all_matching_templates, unused_templates = find_unused_templates(axl, logger, search_text=search_text)
            is_empty = display_results(axl, all_matching_templates, unused_templates, logger, search_text=search_text)

            if not is_empty:
                if should_delete:
                    deleted_count = delete_templates(axl, unused_templates, logger, auto_delete=auto_delete, confirm=confirm)
                else:
                    if prompt_for_deletion(unused_templates, logger):
                        deleted_count = delete_templates(axl, unused_templates, logger, auto_delete=False, confirm=True, skip_initial_prompt=True)
                    else:
                        deleted_count = 0

                if deleted_count > 0:
                    print(f"\n{'=' * 70}")
                    print(f'Successfully deleted {deleted_count} template(s)')
                    print(f"{'=' * 70}\n")
                    logger.info('Deleted %d templates', deleted_count)

    else:
        # No clusters found in CSV - single cluster mode with manual input
        cluster = get_object_for_single_operation(basepath, 'CUCM', server_type='publisher')
        if not cluster:
            print("Error: Unable to load cluster information")
            sys.exit(1)

        username, password = load_credentials('CUCM', cluster['name'])

        server = cluster['server']
        version = cluster['version']

        wsdl_dir = basepath / 'schema' / version / 'AXLAPI.wsdl'
        wsdl = wsdl_dir.absolute().as_uri()
        axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

        all_matching_templates, unused_templates = find_unused_templates(axl, logger, search_text=search_text)
        is_empty = display_results(axl, all_matching_templates, unused_templates, logger, search_text=search_text)

        if not is_empty:
            if should_delete:
                deleted_count = delete_templates(axl, unused_templates, logger, auto_delete=auto_delete, confirm=confirm)
            else:
                if prompt_for_deletion(unused_templates, logger):
                    deleted_count = delete_templates(axl, unused_templates, logger, auto_delete=False, confirm=True, skip_initial_prompt=True)
                else:
                    deleted_count = 0

            if deleted_count > 0:
                print(f"\n{'=' * 70}")
                print(f'Successfully deleted {deleted_count} template(s)')
                print(f"{'=' * 70}\n")
                logger.info('Deleted %d templates', deleted_count)

    logger.info("Clean Unused Phone Button Templates - Completed")
