#!/usr/bin/env python3

import warnings
warnings.simplefilter('ignore')

"""
Delete Softkey Templates from CSV
Reads the output CSV from list_softkey_templates.py and deletes the templates
Only deletes templates with no dependencies (pre-validated by list_softkey_templates.py)

Input CSV format (from list_softkey_templates.py output):
  cluster,name,uuid
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import csv
import urllib3
from setup.logger import setup_logger
from setup.prompt_utils import prompt_yes_no
from setup.multi_object_loader import get_objects_for_multi_operation, load_credentials_for_multi_objects, get_object_for_single_operation, load_credentials
from ucmAPI import AXL


def read_csv_file(csv_path):
    """Read and validate CSV file"""
    templates = []
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row and row.get('name') and row.get('cluster'):
                    templates.append(row)
        return templates
    except Exception as e:
        return None, str(e)


def confirm_deletion(templates, logger):
    """Show templates to be deleted and ask for confirmation"""
    if not templates:
        print("No templates to delete")
        return False

    print(f"\n{'='*80}")
    print(f"Templates to Delete ({len(templates)} templates)")
    print(f"{'='*80}\n")

    clusters_set = set()
    for template in templates:
        print(f"  - {template.get('name')} (Cluster: {template.get('cluster')})")
        clusters_set.add(template.get('cluster'))

    print(f"\nTotal: {len(templates)} templates across {len(clusters_set)} cluster(s)")
    print(f"{'='*80}\n")

    return prompt_yes_no('Delete these templates?', default=False)


def delete_templates_by_cluster(templates, logger):
    """Organize and delete templates by cluster"""
    clusters_data = {}

    for template in templates:
        cluster_name = template.get('cluster')
        if cluster_name not in clusters_data:
            clusters_data[cluster_name] = []
        clusters_data[cluster_name].append(template)

    successful_deletes = 0
    failed_deletes = 0

    # Get all unique clusters from CSV
    unique_clusters = list(clusters_data.keys())
    print(f"\nLoading credentials for {len(unique_clusters)} cluster(s)...")
    print(f"{'='*80}\n")

    # Build cluster data objects for credential loading
    all_clusters_data = get_objects_for_multi_operation(Path.cwd(), 'CUCM', server_type='publisher')
    if not all_clusters_data:
        print("Error: No clusters found in clusters.csv")
        logger.error("No clusters found in clusters.csv")
        return successful_deletes, failed_deletes

    # Filter to only clusters mentioned in CSV
    clusters_to_process = [c for c in all_clusters_data if c.get('name') in unique_clusters]
    if not clusters_to_process:
        print("Error: None of the clusters in CSV found in clusters.csv")
        logger.error("None of the clusters in CSV found in clusters.csv")
        return successful_deletes, failed_deletes

    # Load credentials
    use_same = prompt_yes_no('Use same credentials for all clusters?', default=True)
    cluster_credentials = load_credentials_for_multi_objects('CUCM', clusters_to_process, use_same=use_same)

    # Process each cluster
    for cluster in clusters_to_process:
        cluster_name = cluster.get('name')
        if cluster_name not in clusters_data:
            continue

        try:
            server = cluster.get('server')
            version = cluster.get('version')
            username, password = cluster_credentials[cluster_name]

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            script_dir = Path(__file__).parent
            wsdl_dir = script_dir / 'schema' / version / 'AXLAPI.wsdl'
            wsdl = wsdl_dir.absolute().as_uri()
            axl = AXL(username=username, password=password, wsdl=wsdl, cucm=server, cucm_version=version)

            logger.info('=' * 60)
            logger.info('Processing cluster: %s (%s)', cluster_name, server)
            logger.info('=' * 60)
            print(f"\n{'-'*80}")
            print(f"Processing Cluster: {cluster_name} ({server})")
            print(f"{'-'*80}\n")

            # Delete templates for this cluster
            for template in clusters_data[cluster_name]:
                template_name = template.get('name')
                try:
                    result = axl.delete_softkey_template(template_name)
                    if result.get('success'):
                        print(f"  ✓ Deleted: {template_name}")
                        logger.info('Deleted template: %s', template_name)
                        successful_deletes += 1
                    else:
                        error_msg = result.get('error', 'Unknown error')
                        print(f"  ✗ Failed: {template_name} - {error_msg}")
                        logger.error('Failed to delete template %s: %s', template_name, error_msg)
                        failed_deletes += 1
                except Exception as e:
                    print(f"  ✗ Exception: {template_name} - {str(e)}")
                    logger.error('Exception deleting template %s: %s', template_name, str(e))
                    failed_deletes += 1

            logger.info('Completed cluster: %s', cluster_name)
            print(f"\n✓ Completed {cluster_name}\n")

        except Exception as e:
            logger.error('Failed to process cluster %s: %s', cluster_name, str(e))
            print(f"✗ Failed to process {cluster_name}: {str(e)}\n")
            for template in clusters_data[cluster_name]:
                failed_deletes += 1

    return successful_deletes, failed_deletes


if __name__ == '__main__':
    script_dir = Path(__file__).parent
    basepath = script_dir.parent  # Project root (one level up from cucm/)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Setup Logging
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"_logs/{timestamp}-delete-softkey-templates.log"
    logger = setup_logger(log_file)
    logger.info("Delete Softkey Templates - Started")

    # Get CSV file path
    csv_path = input("Enter path to CSV file from list_softkey_templates.py: ").strip()

    if not csv_path:
        print("Error: CSV file path required")
        logger.error("No CSV file path provided")
        sys.exit(1)

    csv_file = Path(csv_path)

    # If file not found, try looking in _DATA folder
    if not csv_file.exists():
        csv_file = basepath / '_DATA' / csv_path

    if not csv_file.exists():
        print(f"Error: File not found: {csv_path}")
        print(f"Looked in current directory and _DATA folder")
        logger.error("CSV file not found: %s", csv_path)
        sys.exit(1)

    # Read CSV
    print(f"\nReading CSV file: {csv_path}...")
    templates = read_csv_file(csv_file)
    if templates is None:
        print(f"Error: Failed to read CSV file")
        logger.error("Failed to read CSV file: %s", templates)
        sys.exit(1)

    if not templates:
        print("Error: No templates found in CSV file")
        logger.warning("No templates found in CSV file")
        sys.exit(1)

    logger.info('Read %d templates from CSV', len(templates))
    print(f"Successfully read {len(templates)} templates from CSV\n")

    # Confirm deletion
    if not confirm_deletion(templates, logger):
        print("Deletion cancelled by user")
        logger.info("Deletion cancelled by user")
        sys.exit(0)

    # Delete templates
    print("\nDeleting templates...\n")
    successful, failed = delete_templates_by_cluster(templates, logger)

    # Summary
    print(f"\n{'='*80}")
    print(f"Deletion Summary")
    print(f"{'='*80}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total: {successful + failed}")
    print(f"{'='*80}\n")

    logger.info("Deletion Summary - Successful: %d, Failed: %d, Total: %d", successful, failed, successful + failed)
    logger.info("Delete Softkey Templates - Completed")

    sys.exit(0 if failed == 0 else 1)
