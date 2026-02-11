import csv
from datetime import datetime, timezone
from secrets import token_urlsafe
from collections import Counter
from itertools import batched
from typing import List
import pathlib
import logging
import time
import json
import glob
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


FORMATS_Z = [
    "%a %b %d %H:%M:%S %Z %Y",  # Thu Apr 04 14:39:09 UTC 2024
    "%b %d %Y %H:%M:%S %Z",     # Apr 04 2024 00:19:33 UTC
    "%Y-%m-%d %H:%M:%S %Z",     # 2025-12-27 01:16:16 UTC
]

FORMATS_z = [
    "%a %b %d %H:%M:%S %z %Y",  # Thu Apr 04 14:39:09 +0000 2024
    "%b %d %Y %H:%M:%S %z",     # Apr 04 2024 00:19:33 +0000
    "%Y-%m-%d %H:%M:%S %z",     # 2025-12-27 01:16:16 UTC
    "%Y-%m-%dT%H:%M:%S.%f%z",     # 2025-12-27T01:16:16.000Z
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


def render_message(dir_path, message, meta: dict,):
    """
    Returns a paradigm formatted message
    :param dir_path:
    :param message:
    :param meta: metadata passed in from the main function
    :return:
    """
    return {
        "platform": "synchronoss",
        "platformValues": {
            "messageType": 'sms' if 'sms' in dir_path else 'mms',
            "senderId": 'sent' if 'out' in dir_path else 'received',
        },
        "dirId": meta['dirId'],
        "messageId": token_urlsafe(16),
        "msgDate": pathlib.Path(dir_path).name,
        "msgFrom": 'sent' if 'out' in dir_path else 'received',
        "msgBody": message,
        "messageType": 'sms' if 'sms' in dir_path else 'mms',
    }

def render_message_csv(row, meta: dict,):
    """
    Returns a paradigm formatted message
    :param row: current row being processed in file
    :param meta: metadata passed in from the main function
    :return:
    """
    return {
        "platform": "synchronoss",
        "platformValues": {
            "messageType": row['Type'],
            "senderId": row['Sender'],
            "recipientId": row['Recipients'],
            "messageId": row['Message ID'],
            "attachments": row['Attachments'],
            "direction": row['Direction'],
        },
        "dirId": meta['dirId'],
        "messageId": token_urlsafe(16),
        "msgDate": to_iso_utc(row['Date']),
        "msgFrom": row['Sender'],
        "msgTo": row['Recipients'],
        "msgBody": row['Body'],
        "messageType": row['Type'],
    }


def get_messages_text_docs(root_path, meta: dict, summary: list, activities: list):
    """
    :param root_path: The sms/mms `in` and sms/mms `out` folder path passed from the main function.
    :param meta: The metadata passed from the main function.
    :param summary:
    :param activities:
    :return:
    """

    # For summary.append below
    counts = Counter()
    start = time.time()

    # Grabs all the files stored in the sms/mms `in` or `out` folder passed in from the main function
    filenames = glob.glob(f'{root_path}/**/*.txt', recursive=True)

    # Process 100 hundred files before passing the data to Paradigm
    for batch in batched(filenames, 100):
        for filename in batch:
            # Skip empty files
            if os.path.getsize(filename) == 0:
                continue
            # Count how many 'mms' or 'sms' messages have been received or sent
            counts[pathlib.Path(root_path).parent.name] += 1
            with open(os.path.join(root_path, filename), 'r', encoding='utf-8') as fd:
                msg = fd.read()
                print(json.dumps({"type": "message", "data":
                    render_message(root_path, msg.replace("\n", " "), meta)}, ensure_ascii=False), flush=True)
                # tag activity
                activities.append({
                    "type": "data",
                    "dirId": meta['dirId'],
                    "platform": "synchronoss",
                    "date": pathlib.Path(root_path).name,  # The messages are stored in folders that are named after
                    "caseId": None,                        # the date the messages were sent or received
                    "event": "message",
                })

        duration = time.time() - start

        summary.append({
            "file": os.path.basename(root_path),
            "time_taken_secs": round(duration, 2),
            "messages": sum(counts.values()),
            "breakdown": dict(counts)
        })


def get_messages_csv_docs(root_path, meta: dict, summary: list, activities: list, uniqueUsers: set):
    """
        :param root_path: The messages folder path passed from the main function.
        :param meta: The metadata passed from the main function.
        :param summary:
        :param activities:
        :param uniqueUsers:
        """

    # For summary.append below
    counts = Counter()
    start = time.time()

    # Grabs all the files stored in the sms/mms `in` or `out` folder passed in from the main function
    filenames = glob.glob(f'{root_path}/**/*.csv', recursive=True)

    # Process 100 hundred files before passing the data to Paradigm
    for batch in batched(filenames, 50):
        for filename in batch:
            with open(filename, 'r', encoding='utf-8') as fd:
                dict_reader = csv.DictReader(fd)
                for row in dict_reader:
                    counts[row['Type']] += 1
                    print(json.dumps({"type": "message", "data": render_message_csv(row, meta)},
                                     ensure_ascii=False), flush=True)
                    # tag activity
                    activities.append({
                        "type": "data",
                        "dirId": meta['dirId'],
                        "platform": "synchronoss",
                        "date": to_iso_utc(row["Date"]),
                        "caseId": None,  # the date the messages were sent or received
                        "event": "message",
                    })

                    # row['Sender'] and row['Recipients'] are each telephone numbers with different formats. Some use
                    # +, or use +1, or have just a 10-digit number. Capture just the 10-digit number in either of the
                    # cases.
                    if sender := re.findall(r'\+?1?(\d{10})', row['Sender']):
                        uniqueUsers.add(sender[0])
                    elif recipient := re.findall(r'\+?1?(\d{10})', row['Recipients']):
                        uniqueUsers.add(recipient[0])

        duration = time.time() - start


        summary.append({
            "file": os.path.basename(root_path),
            "time_taken_secs": round(duration, 2),
            "messages": sum(counts.values()),
            "breakdown": dict(counts)
        })


# Command Line Interface (CLI)
def main(argv: List[str]) -> int:
    """
    :param argv: A list of command line arguments argv[0] = python script, argv[1] = [run|info], argv[2] = filepath
    :return:
    """
    # Variables to store data collected during processing..
    activities = []
    uniqueUsers = set()
    uniqueIPs = set()
    integrityId = token_urlsafe(16)
    summary = []
    meta = {
        "dirId": integrityId,
        "dateRun": datetime.now(timezone.utc).isoformat()
    }

    # Command line variable processing
    if dir_path := parse_cmd_line(argv):
        # Synchronoss uses the subscriber 10 digit telephone number as the account number. Their returns are therefore
        # provided in a directory/folder that uses the telephone number as its name. Assuming the user selects this
        # folder as the folder Paradigm will process, capture the directory/folder name. If the user does not select
        # this folder then do not capture the folder name.
        if re.match(r"^\d{10}", pathlib.Path(dir_path).name):
            uniqueUsers.add(pathlib.Path(dir_path).name)

        exclude_dir = ['call', 'VZMOBILE', 'attachments']
        # Process all the files and folders found in dir_path except those listed in exclude_dir. These directories
        # do not provide any intel.
        for root_folder, subfolders, filenames in os.walk(os.path.normpath(dir_path), topdown=True):
            # Exclude directories based on exclude_dir list above.
            subfolders[:] = [d for d in subfolders if d not in exclude_dir]

            # The 'sms' and 'mms' folders each contain two folders. One named 'in' the other named 'out'. The 'in' and
            # 'out' folders can contain multiple folders. Each of these folders is named according to the date
            # YYYY-MM-DD messages were received or sent. Each of these dated folders can contain multiple text files
            # inside. Each of these text files contains the message sent or received. One text file per message.
            if 'sms' in root_folder or 'mms' in root_folder:
                # Process all the files in the sms or mms in directory.
                if 'in' == pathlib.Path(root_folder).name:
                    get_messages_text_docs(root_folder, meta, summary, activities)
                # Process all the files in the sms or mms out directory
                if 'out' == pathlib.Path(root_folder).parent.name:
                    get_messages_text_docs(root_folder, meta, summary, activities)
            # Capture new format using CSV files instead of TXT files
            if 'messages' in root_folder:
                get_messages_csv_docs(root_folder, meta, summary, activities, uniqueUsers,)

            if filenames:
                for file in filenames:
                    if file.endswith('.xlsx'):
                        print(f'Found an Excel file at {root_folder}')

        # Print final Summary
        print(json.dumps({"type": "plugin_summary", "data": {
            "company": "Synchronoss",
            "dirId": meta['dirId'],
            "summary": summary,
            "uniqueUsers": list(uniqueUsers),
            "uniqueUserCount": len(uniqueUsers),
            "activities": activities,
            "activityCount": len(activities),
        }}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
