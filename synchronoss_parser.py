
from datetime import datetime, timezone
from secrets import token_urlsafe
from bs4 import BeautifulSoup
from typing import List
import pathlib
import logging
import json
import sys
import os
import re

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)  # Python 3.7+
# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stderr
)


def show_info():
    print(json.dumps({
        "name": "Yahoo Parser",
        "description": "Processes Yahoo documents, extracts messages, IPs, locations, and gives a summary.",
        "author": "Pathfinder Labs",
        "created": "2026-02-01",
        "version": "1.0.0",
        "dataType": "data",
        "usage": "python script.py run <directory>\npython script.py info",
        "notes": "Handles html and csv files",
        "fileTypes": ["html, csv"]
    }))


# List of datetime formats for to_iso_utc()
# List of datetime formats for to_iso_utc()
FORMATS_Z = [
    "%a %b %d %H:%M:%S %Z %Y",  # Thu Apr 04 14:39:09 UTC 2024
    "%b %d %Y %H:%M:%S %Z",     # Apr 04 2024 00:19:33 UTC
    "%Y-%m-%d %H:%M:%S %Z",     # 2025-12-27 01:16:16 UTC
    "%Y-%m-%d %H:%M:%S",        # 2025-12-27 01:16:16

]

FORMATS_z = [
    "%a %b %d %H:%M:%S %z %Y",  # Thu Apr 04 14:39:09 +0000 2024
    "%b %d %Y %H:%M:%S %z",     # Apr 04 2024 00:19:33 +0000
    "%Y-%m-%d %H:%M:%S %z",     # 2025-12-27 01:16:16 UTC
    "%Y-%m-%d %H:%M:%S.%f%z",   # 2025-12-27 01:16:160000+00:00
    "%Y-%m-%d %H:%M:%S%z",      # 2025-12-27 01:16:16+00:00
]


def to_iso_utc(ts: str) -> str:
    # First try with %Z (named timezone)
    for fmt in FORMATS_Z:
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass

    # Normalize " UTC " to "+0000" so %z parses reliably, then try %z formats
    ts_fixed = ts.replace(" UTC ", " +0000 ").replace(" UTC", " +0000")
    for fmt in FORMATS_z:
        try:
            dt = datetime.strptime(ts_fixed, fmt)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass

    raise ValueError(f"Unrecognized date format: {ts}")


def get_subscriber_data(html_file, meta: dict, activities: list, uniquePeople: set, uniqueUsers: set, uniqueIPs: set):
    soup = BeautifulSoup(open(html_file), 'html.parser')
    for ul in soup.find_all('ul'):
        if ul:
            li = ul.find_all('li')
            for item in li:
                print(f'{item}')


# Command Line Interface (CLI)
def main(argv: List[str]) -> int:
    """
    :param argv: A list of command line arguments argv[0] = python script, argv[1] = [run|info], argv[2] = filepath
    :return:
    """
    # Variables to store data collected during processing..
    activities = []
    uniquePeople = set()
    uniqueUsers = set()
    uniqueIPs = set()
    uniqueLocations = set()
    uniqueDevices = []
    integrityId = token_urlsafe(16)
    meta = {
        "dirId": integrityId,
        "dateRun": datetime.now(timezone.utc).isoformat()
    }

    # Command line variable processing
    if len(argv) < 2:
        print("Usage: python yahoo_parser.py [info|run]", file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == 'info':
        show_info()
        return 0
    if cmd == 'run':
        if len(argv) < 3:
            print("Please provide the path to the (extracted) Yahoo return folder: "
                  "yahoo_parser.py run <folder path>", file=sys.stderr)
            return 2
        dir_path = sys.argv[2]
        if not dir_path:
            logging.error('Folder path not provided.')
            sys.exit(1)
        else:
            # Process all the files and folders found in dir_path
            for root_folder, subfolders, filenames in os.walk(os.path.normpath(dir_path), topdown=True):
                # Process all the files inside the root_folder and all subfolders
                for filename in filenames:
                    # filename sanity check before passing it along. If an exception is thrown during this test
                    # skip the file and move on.
                    try:
                        path = pathlib.Path(filename)
                        path.resolve()
                    except Exception as e:
                        logging.error(f"filename `{filename}` is not valid: {e}")
                        continue
                    # Get the full filepath for the file currently being processed.
                    file_path = os.path.join(root_folder, filename)
                    if '-subscriber_details-' in file_path:
                        get_subscriber_data(file_path, meta, activities, uniquePeople, uniqueUsers, uniqueIPs)

            # Print final Summary
            print(json.dumps({"type": "plugin_summary", "data": {
                "company": "Google",
                "dirId": integrityId,
                "uniquePeople": list(uniquePeople),
                "uniquePeopleCount": len(uniquePeople),
                "uniqueLocations": list(uniqueLocations),
                "uniqueLocationCount": len(uniqueLocations),
                "uniqueUsers": list(uniqueUsers),
                "uniqueUserCount": len(uniqueUsers),
                "uniqueIPs": list(uniqueIPs),
                "uniqueIPCount": len(uniqueIPs),
                "activities": activities,
                "activityCount": len(activities),
            }}, ensure_ascii=False), flush=True)
            return 0
    else:
        print("Unknown command. Use 'info' or 'run'.", file=sys.stderr)
        logging.info("Unknown command. Use 'info' or 'run'.")
        return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

