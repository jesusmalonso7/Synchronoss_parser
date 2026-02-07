from datetime import datetime, timezone
from secrets import token_urlsafe
from collections import Counter
from typing import List
import pathlib
import logging
import time
import json
import sys
import os

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)  # Python 3.7+
# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stderr
)


def show_info():
    print(json.dumps({
        "name": "Synchronoss Parser",
        "description": "Processes Synchronoss text files for sms/mms text messages and provide a summary.",
        "author": "Pathfinder Labs",
        "created": "2026-02-05",
        "version": "1.0.0",
        "dataType": "data",
        "usage": "python script.py run <directory>\npython script.py info",
        "notes": "Handles TXT files",
        "fileTypes": ["txt"]
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


def parse_cmd_line(argv: list) -> str:
    # Command line variable processing
    if len(argv) < 2:
        print("Usage: python synchronoss_parser.py [info|run]", file=sys.stderr)
        sys.exit(2)
    cmd = argv[1]
    if cmd == 'info':
        show_info()
        sys.exit(0)
    if cmd == 'run':
        if len(argv) < 3:
            print("Please provide the path to the (extracted) Synchronoss return folder: "
                  "synchronoss_parser.py run <folder path>", file=sys.stderr)
            sys.exit(2)
        dir_path = sys.argv[2]
        if not dir_path:
            logging.error('Folder path not provided.')
            sys.exit(1)
        else:
            return dir_path
    else:
        print("Unknown command. Use 'info' or 'run'.", file=sys.stderr)
        logging.info("Unknown command. Use 'info' or 'run'.")
        sys.exit(2)


def files_need_processing(root_path: str) -> bool:
    """
    :param root_path:
    :return: number of files processed that are not empty
    :Description: Small utility tool to quickly assess if there are any text files in a folder that have information.
                  Used to preemptively ignore folders with large quantities of empty text files.
    """

    # os.walk() starts traversing directories from sms/in or sms/out passed in from the main function.
    for root_folder, subfolders, filenames in os.walk(os.path.normpath(root_path), topdown=True):
        for filename in filenames:
            # Many of the text files are empty. Skip those
            if filename.endswith('.txt') and os.path.getsize(f'{os.path.join(root_folder, filename)}') > 0:
                return True
    return False


def render_message(dir_path, message, integrityId):
    """
    Returns a paradigm formatted message
    :param dir_path:
    :param message:
    :param integrityId:
    :return:
    """
    return {
        "platform": "synchronoss",
        "platformValues": {
            "messageType": 'sms' if 'sms' in dir_path else 'mms',
            "senderId": 'sent' if 'out' in dir_path else 'received',
        },
        "dirId": integrityId,
        "messageId": token_urlsafe(16),
        "messageType": "message",
        "msgBody": message,
        "msgDate": pathlib.Path(dir_path).name,

    }


def get_messages(root_path, meta, summary, integrityId, activities):
    """
    :param root_path: The sms/in and sms/out path passed from the main function.
    :param meta: The meta data passed from the main function.
    :param summary:
    :param integrityId: The integrity id passed from the main function.:
    :param activities:
    :return:
    """

    counts = Counter()
    start = time.time()

    filenames = os.listdir(root_path)

    for filename in filenames:
        # Keep track of message type count. pathlib.Path(root_path).parent.name returns either 'sms' or 'mms'
        counts[pathlib.Path(root_path).parent.name] += 1
        # Many of the text files are empty. Skip those
        if filename.endswith('.txt') and os.path.getsize(f'{os.path.join(root_path, filename)}') > 0:
            with open(os.path.join(root_path, filename), 'r', encoding='utf-8') as fd:
                msg = fd.read()
                print(json.dumps({"type": "message", "data": render_message(root_path, msg.replace("\n", " "), integrityId)}, ensure_ascii=False), flush=True)
                # Create activity
                activities.append({
                    "type": "data",
                    "dirId": meta,
                    "platform": "synchronoss",
                    "date": pathlib.Path(root_path).name,
                    "caseId": None,
                    "event": 'sms' if 'sms' in pathlib.Path(root_path).parent.parent.name else 'mms',
                })

    duration = time.time() - start

    summary.append({
        "file": os.path.basename(root_path),
        "time_taken_secs": round(duration, 2),
        "messages": sum(counts.values()),
        "breakdown": dict(counts)
    })


def render_message(dir_path, message, integrityId):
    """
    Returns a paradigm formatted message
    :param dir_path:
    :param message:
    :param integrityId:
    :return:
    """
    return {
        "platform": "synchronoss",
        "dirId": integrityId,
        "messageId": token_urlsafe(16),
        "msgFrom": 'sent' if 'out' in dir_path else 'received',
        "messageType": 'sms' if 'sms' in dir_path else 'mms',
        "msgBody": message,
        "msgDate": pathlib.Path(dir_path).name,
    }


# Command Line Interface (CLI)
def main(argv: List[str]) -> int:
    """
    :param argv: A list of command line arguments argv[0] = python script, argv[1] = [run|info], argv[2] = filepath
    :return:
    """
    # Variables to store data collected during processing..
    activities = []
    integrityId = token_urlsafe(16)
    summary = []
    meta = {
        "dirId": integrityId,
        "dateRun": datetime.now(timezone.utc).isoformat()
    }

    # Command line variable processing
    if dir_path := parse_cmd_line(argv):
        # Prevents os.walk() from processing these directories. These directories do not contain any data of value.
        exclude_dir = ['call', 'VZMOBILE',]
        # Process all the files and folders found in dir_path
        for root_folder, subfolders, filenames in os.walk(os.path.normpath(dir_path), topdown=True):
            # Exclude directories based on exclude_dir list above.
            subfolders[:] = [d for d in subfolders if d not in exclude_dir]

            if 'sms' in root_folder or 'mms' in root_folder:
                # if 'in' == pathlib.Path(root_folder).parent.name:
                #     if 'in' == pathlib.Path(root_folder).parent.name:
                #         if files_need_processing(root_folder):
                #             get_messages(root_folder, meta, summary, integrityId, activities)
                if 'out' == pathlib.Path(root_folder).parent.name:
                        if 'out' == pathlib.Path(root_folder).parent.name:
                            if files_need_processing(root_folder):
                                get_messages(root_folder, meta, summary, integrityId, activities)

        # Print final Summary
        print(json.dumps({"type": "plugin_summary", "data": {
            "company": "Synchronoss",
            "dirId": integrityId,
            "activities": activities,
            "activityCount": len(activities),
        }}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
