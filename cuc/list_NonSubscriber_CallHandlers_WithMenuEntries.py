#!/usr/bin/env python3
"""Export all non-subscriber Cisco Unity Connection call handlers and menu entries."""

from pathlib import Path
import csv
import getpass
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry
import urllib3
from lxml import etree

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PAGE_SIZE = 2000
REQUEST_TIMEOUT = 60
MENU_REQUEST_DELAY_SECONDS = 0
LOG_FILENAME_PREFIX = "export-Unity-CallHandler-TreeData-"

SKIP_HANDLERS = {
    "Opening Greeting",
    "Operator",
    "Goodbye",
    "undeliverablemessagesmailbox",
    "operator",
}


def setup_logger(log_path):
    logger = logging.getLogger("cuc_logger")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def load_server_config(config_file):
    with open(config_file, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    missing = [key for key in ("server", "username") if not config.get(key)]
    if missing:
        raise ValueError("Missing required JSON field(s): " + ", ".join(missing))
    return config


def create_session(username, password):
    session = requests.Session()
    session.auth = HTTPBasicAuth(username, password)
    session.headers.update({"Accept": "application/xml"})
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def element_to_dict(element):
    return {child.tag: child.text for child in element}


def clean(value):
    return str(value).strip() if value is not None else ""


def get_non_subscriber_call_handlers(session, cuc_server, logger):
    base_url = f"https://{cuc_server}/vmrest/handlers/callhandlers"
    page_number = 1
    total_reported = None
    raw_count = 0
    subscriber_count = 0
    non_subscriber_count = 0
    skipped_system_count = 0
    handlers = []
    all_handlers_by_id = {}
    seen_object_ids = set()

    logger.info("Retrieving Call Handlers from %s", cuc_server)

    while True:
        response = session.get(
            base_url,
            params={"rowsPerPage": PAGE_SIZE, "pageNumber": page_number},
            verify=False,
            timeout=REQUEST_TIMEOUT,
        )
        logger.info(
            "Page %d - HTTP Status: %d - URL: %s",
            page_number, response.status_code, response.url,
        )
        if not response.ok:
            logger.error("Unity response body: %s", response.text[:2000])
        response.raise_for_status()

        root = etree.fromstring(response.content)

        if total_reported is None:
            total_text = root.get("total")
            total_reported = int(total_text) if total_text else None
            if total_reported is not None:
                logger.info("Unity reports %d total handler records", total_reported)
                logger.info(
                    "Expected pages at page size %d: %d",
                    PAGE_SIZE, math.ceil(total_reported / PAGE_SIZE),
                )

        page_elements = root.findall(".//Callhandler")
        page_count = len(page_elements)
        if page_count == 0:
            break

        page_new_ids = 0
        page_non_subscribers = 0

        for element in page_elements:
            item = element_to_dict(element)
            object_id = clean(item.get("ObjectId"))
            if object_id and object_id in seen_object_ids:
                continue
            if object_id:
                seen_object_ids.add(object_id)
                page_new_ids += 1
            raw_count += 1


            # Keep a lightweight lookup for every handler, including subscribers.
            if object_id:
                all_handlers_by_id[object_id] = {
                    "displayName": clean(item.get("DisplayName")),
                    "isSubscriber": bool(item.get("RecipientSubscriberObjectId")),
                }

            if item.get("RecipientSubscriberObjectId"):
                subscriber_count += 1
                continue

            non_subscriber_count += 1
            page_non_subscribers += 1
            display_name = clean(item.get("DisplayName"))
            if display_name in SKIP_HANDLERS:
                skipped_system_count += 1
                continue

            handlers.append({
                "displayName": display_name,
                "extension": clean(item.get("DtmfAccessId")),
                "objectId": object_id,
                "uri": clean(item.get("URI")),
            })

        logger.info(
            "Page %d summary: returned=%d, new IDs=%d, non-subscriber=%d",
            page_number, page_count, page_new_ids, page_non_subscribers,
        )

        if page_count < PAGE_SIZE:
            break
        if total_reported is not None and raw_count >= total_reported:
            break
        if page_new_ids == 0:
            raise RuntimeError(
                "Unity repeated a page with no new ObjectIds. "
                "Verify that pageNumber is supported and honored."
            )
        page_number += 1

    handlers.sort(key=lambda row: (row["displayName"].casefold(), row["objectId"]))
    logger.info("Raw unique handler records processed: %d", raw_count)
    logger.info("Subscriber handlers excluded: %d", subscriber_count)
    logger.info("Non-subscriber handlers found: %d", non_subscriber_count)
    logger.info("Built-in/system handlers excluded: %d", skipped_system_count)
    logger.info("Call handlers to export: %d", len(handlers))
    logger.info("All-handler lookup records retained: %d", len(all_handlers_by_id))
    if total_reported is not None and raw_count != total_reported:
        logger.warning(
            "Unity reported %d total records, but %d unique records were processed",
            total_reported, raw_count,
        )
    return handlers, all_handlers_by_id
def write_call_handlers_csv(handlers, csv_file, logger):
    fields = ["displayName", "extension", "objectId", "uri"]
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(handlers)
    logger.info("Exported %d Call Handlers to %s", len(handlers), csv_file)


def classify_destination(entry, target_handler_name, subscriber_name):
    transfer_number = clean(entry.get("TransferNumber"))
    transfer_display_name = clean(entry.get("DisplayName"))
    target_handler_id = clean(entry.get("TargetHandlerObjectId"))
    target_conversation = clean(entry.get("TargetConversation"))

    if transfer_number:
        return "Transfer", transfer_display_name or transfer_number

    if target_handler_id:
        if target_handler_name:
            return "Call Handler", target_handler_name
        if subscriber_name:
            return "Subscriber Mailbox", subscriber_name
        return "Unknown Handler", target_handler_id

    if target_conversation:
        return "Conversation", target_conversation

    return "No configured destination", ""

def get_menu_entries(session, cuc_server, handlers, all_handlers_by_id, logger):
    name_by_id = {
        row["objectId"]: row["displayName"]
        for row in handlers if row["objectId"]
    }
    output = []
    errors = []
    total_handlers = len(handlers)
    logger.info("Retrieving MenuEntries for %d Call Handlers", total_handlers)

    for index, handler in enumerate(handlers, start=1):
        source_name = handler["displayName"]
        source_id = handler["objectId"]
        menu_url = (
            f"https://{cuc_server}/vmrest/handlers/callhandlers/"
            f"{source_id}/menuentries"
        )
        try:
            response = session.get(
                menu_url, verify=False, timeout=REQUEST_TIMEOUT
            )
            if not response.ok:
                logger.error(
                    "MenuEntries failed for %s: HTTP %d - %s",
                    source_name, response.status_code, response.text[:1000],
                )
            response.raise_for_status()
            root = etree.fromstring(response.content)
            menu_elements = root.findall(".//MenuEntry")

            for element in menu_elements:
                entry = element_to_dict(element)
                target_id = clean(entry.get("TargetHandlerObjectId"))
                target_name = name_by_id.get(target_id, "")
                subscriber_name = ""
                if (
                    not target_name
                    and target_id in all_handlers_by_id
                    and all_handlers_by_id[target_id]["isSubscriber"]
                ):
                    subscriber_name = (
                        all_handlers_by_id[target_id]["displayName"]
                    )
                destination_type, destination_name = classify_destination(
                    entry, target_name, subscriber_name
                )
                locked = clean(entry.get("Locked")).lower()
                if locked == "true":
                    locked = "TRUE"
                elif locked == "false":
                    locked = "FALSE"
                else:
                    locked = ""

                output.append({
                    "sourceHandler": source_name,
                    "sourceExtension": handler["extension"],
                    "sourceObjectId": source_id,
                    "touchToneKey": clean(entry.get("TouchtoneKey")),
                    "locked": locked,
                    "actionCode": clean(entry.get("Action")),
                    "destinationType": destination_type,
                    "destinationName": destination_name,
                    "targetConversation": clean(entry.get("TargetConversation")),
                    "targetHandlerObjectId": target_id,
                    "targetHandlerName": target_name,
                    "transferDisplayName": clean(entry.get("DisplayName")),
                    "transferNumber": clean(entry.get("TransferNumber")),
                    "transferType": clean(entry.get("TransferType")),
                    "transferRings": clean(entry.get("TransferRings")),
                    "menuEntryObjectId": clean(entry.get("ObjectId")),
                    "menuEntryUri": clean(entry.get("URI")),
                })

            logger.info(
                "MenuEntries %d/%d: %s - %d entries",
                index, total_handlers, source_name, len(menu_elements),
            )

        except Exception as exc:
            logger.error("Unable to process MenuEntries for %s: %s", source_name, exc)
            errors.append({
                "sourceHandler": source_name,
                "sourceExtension": handler["extension"],
                "sourceObjectId": source_id,
                "menuUrl": menu_url,
                "error": str(exc),
            })

        if MENU_REQUEST_DELAY_SECONDS > 0:
            time.sleep(MENU_REQUEST_DELAY_SECONDS)

    key_order = {str(i): i for i in range(10)}
    key_order.update({"*": 10, "#": 11})
    output.sort(key=lambda row: (
        row["sourceHandler"].casefold(),
        key_order.get(row["touchToneKey"], 99),
        row["destinationName"].casefold(),
    ))
    logger.info("Collected %d total MenuEntry records", len(output))
    logger.info("MenuEntry handler failures: %d", len(errors))
    return output, errors


def write_menu_entries_csv(rows, csv_file, logger):
    fields = [
        "sourceHandler", "sourceExtension", "sourceObjectId", "touchToneKey",
        "locked", "actionCode", "destinationType", "destinationName",
        "targetConversation", "targetHandlerObjectId", "targetHandlerName",
        "transferDisplayName", "transferNumber", "transferType", "transferRings",
        "menuEntryObjectId", "menuEntryUri",
    ]
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Exported %d MenuEntry records to %s", len(rows), csv_file)


def write_errors_csv(errors, csv_file, logger):
    fields = ["sourceHandler", "sourceExtension", "sourceObjectId", "menuUrl", "error"]
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(errors)
    logger.info("Exported %d MenuEntry errors to %s", len(errors), csv_file)


def main():
    config_input = input("CUC JSON File (cuc-info.json): ").strip()
    config_file = Path(config_input or "cuc-info.json")
    if not config_file.exists():
        print(f"Error: Config file {config_file} not found")
        sys.exit(1)

    handler_input = input(
        "Call Handler CSV Output (non_subscriber_callhandlers.csv): "
    ).strip()
    handler_csv = Path(handler_input or "non_subscriber_callhandlers.csv")

    menu_input = input("Menu Entry CSV Output (menuentries.csv): ").strip()
    menu_csv = Path(menu_input or "menuentries.csv")
    error_csv = menu_csv.with_name(menu_csv.stem + "_errors.csv")

    try:
        config = load_server_config(config_file)
        cuc_server = clean(config["server"])
        username = clean(config["username"])
        password = config.get("password") or getpass.getpass("CUC Password: ")

        base_path = Path(__file__).resolve().parent
        safe_server = cuc_server.replace(":", "_").replace("/", "_")
        log_path = (
            base_path / "logs" /
            f"{LOG_FILENAME_PREFIX}{safe_server}-{time.strftime('%Y_%m_%d-%H_%M_%S')}.log"
        )
        logger = setup_logger(log_path)
        session = create_session(username, password)

        handlers, all_handlers_by_id = get_non_subscriber_call_handlers(
            session, cuc_server, logger
        )
        write_call_handlers_csv(handlers, handler_csv, logger)

        menu_entries, errors = get_menu_entries(
            session, cuc_server, handlers, all_handlers_by_id, logger
        )
        write_menu_entries_csv(menu_entries, menu_csv, logger)
        write_errors_csv(errors, error_csv, logger)

        print("\nUnity export completed successfully.")
        print(f"Call Handlers: {handler_csv}")
        print(f"Menu Entries: {menu_csv}")
        print(f"Menu Entry Errors: {error_csv}")
        logger.info("Unity Call Handler and MenuEntry export completed successfully")

    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(130)
    except Exception as exc:
        try:
            logger.exception("Script failed: %s", exc)
        except NameError:
            print(f"Script failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
