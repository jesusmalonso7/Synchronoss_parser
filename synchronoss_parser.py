from datetime import datetime, timezone
from secrets import token_urlsafe
from collections import Counter
from itertools import batched
from typing import List
import pandas as pd
import phonenumbers
import pathlib
import logging
import ijson
import time
import json
import glob
import csv
import sys
import os
import io
import re

if isinstance(sys.stdout, io.TextIOWrapper):
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
        "description": "Processes Synchronoss text, xlsx, or csv files and provide a summary. "
                       "To begin processing please select the unzipped Synchronoss return",
        "author": "Pathfinder Labs",
        "created": "2026-02-05",
        "last_updated": "2026-08-16",
        "version": "1.2.2",
        "dataType": "data",
        "usage": "synchronoss_parser.py run <directory>\nsynchronoss_parser.py info",
        "notes": "Handles TXT, CSV and XLSX files",
        "fileTypes": ["txt, csv, xlsx"]
    }))


FORMATS_Z = [
    "%a %b %d %H:%M:%S %Z %Y",  # Thu Apr 04 14:39:09 UTC 2024
    "%b %d %Y %H:%M:%S %Z",     # Apr 04 2024 00:19:33 UTC
    "%Y-%m-%d %H:%M:%S %Z",     # 2025-12-27 01:16:16 UTC
    "%Y-%m-%d %H:%M:%S",        # 2025-10-22 01:36:18
]

FORMATS_z = [
    "%a %b %d %H:%M:%S %z %Y",  # Thu Apr 04 14:39:09 +0000 2024
    "%b %d %Y %H:%M:%S %z",     # Apr 04 2024 00:19:33 +0000
    "%d/%b/%Y:%H:%M:%S %z",     # 03/Oct/2024:08:58:31 +0000
    "%Y-%m-%d %H:%M:%S %z",     # 2025-12-27 01:16:16 UTC
    "%Y-%m-%dT%H:%M:%S.%f%z",   # 2025-12-27T01:16:16.000Z
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


def get_phone_number(lineOfText: str) -> list:
    """
    :param lineOfText: A text string that may or may not contain the phone number
    :return: Return a list of all the phone numbers
    """
    # The default region is set to 'US'. A default is required. If the phone
    # number cannot be identified for the default region and international check
    # will be completed.
    numbers = phonenumbers.PhoneNumberMatcher(lineOfText, 'US')
    return [phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164) for match in numbers]


def get_vcard_info(vcf_file, uniqueUsers: set, uniquePeople: set, uniqueDevices: set) -> dict:
    """
    :param vcf_file: This is actually a .vcf is actually a vCard which contains contact information
    :param uniqueUsers: List of unique users
    :param uniquePeople: List of unique people
    :param uniqueDevices: List of unique devices
    """
    vCard_data = {}
    # The .vcf card will be processed as a text file. If you double-click on the actual .vcf file it will open it
    # as a contact card in Windows. Problem is that Windows does not show all the data. When the .vcf card is open
    # as a text file additional information, another email address, was found.
    with open(vcf_file, 'r') as f:
        for line in f.readlines():
            if line.startswith("CUSTOM.EMAIL:"):
                vCard_data["Email"] = line.split(":")[1].strip()
            # FN is for full name. User sometimes put the email address in this field. The `elif` test to see if `@`
            # is part of the FN. If it is the entry may be an email address.
            elif line.startswith("FN:"):
                if '@' not in line:
                    vCard_data["Contact Name"] = line.split(":")[1].strip()
                # Some users place an email address where the name should go. Capture this as a
                # second email.
                elif '@' in line:
                    vCard_data['Additional Email'] = line.split(":")[1].strip()
            elif line.startswith('TEL;type=pref: '):
                vCard_data["Preferred Phone#"] = line.split(":")[1].strip()
            elif line.startswith('TEL;CELL:'):
                vCard_data["Cellphone#"] = line.split(":")[1].strip()
            elif line.startswith('PRODID:'):
                vCard_data["Device ID"] = line.split(":")[1].replace('-','').replace('//', ' ').strip()
            elif line.startswith('URL;type=pref:'):
                vCard_data["URL"] = line.split("URL;type=pref:")[1].replace('\\', '').strip()

        # Make sure the dictionary has at least one valid value before sending the data to Paradigm
        if any(vCard_data.values()):
            # Build string to display contents of the contact card to user via Paradigms Identities tab.
            build_vCard_str = '(vCard Contact) '
            for k, v in vCard_data.items():
                build_vCard_str += f'{k}: {v}, '
            uniqueUsers.add(build_vCard_str)
            if "Device" in vCard_data.keys():
                uniqueDevices.add(vCard_data["Device"])
            if "Name" in vCard_data.keys():
                uniquePeople.add(vCard_data["Name"] if vCard_data["Name"] else "")

        uniquePeople.discard(None)
        uniquePeople.discard('')

        return vCard_data

def render_text_messages(dir_path, message, meta: dict,):
    """
    Returns a paradigm formatted message. This render_text_messages was written for Synchronoss returns provided in text
    format. These files are stored in the sms and mms folders of the return.
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


def render_csv_messages(row, meta: dict,):
    """
    :param row: current row being processed in file
    :param meta: metadata passed in from the main function
    :return: a paradigm formatted message for Synchronoss returns provided in CSV format stored in the messages-folder.
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


def get_text_messages(root_path, meta: dict, activities: list):
    """
    :param root_path: The sms/mms `in` and sms/mms `out` folder path passed from the main function.
    :param meta: The metadata passed from the main function.
    :param activities:
    """

    # Grabs all the files stored in the sms/mms `in` or `out` folder passed in from the main function
    filenames = glob.glob(f'{root_path}/**/*.txt', recursive=True)

    # Process 50 files before passing the data to Paradigm
    for batch in batched(filenames, 50):
        for filename in batch:
            # The messages are stored in folders that are named after the date the messages were sent or received
            date = pathlib.Path(filename).parent.name
            # Skip empty files
            if os.path.getsize(filename) == 0:
                continue
            with open(os.path.join(root_path, filename), 'r', encoding='utf-8') as fd:
                msg = fd.read()
                print(json.dumps({"type": "message", "data":
                    render_text_messages(root_path, msg.replace("\n", " "), meta)}, ensure_ascii=False), flush=True)
                # tag activity
                activities.append({
                    "type": "data",
                    "dirId": meta['dirId'],
                    "platform": "synchronoss",
                    "date": date,
                    "caseId": None,
                    "event": "message",
                })


def get_csv_messages(message_folder_path, meta: dict, summary: list, activities: list, uniqueUsers: set):
    """
        :param message_folder_path:
        :param meta: The metadata passed from the main function.
        :param summary:
        :param activities:
        :param uniqueUsers:
        """

    # For summary.append below
    counts = Counter()
    start = time.time()

    # Grabs all the files stored in the message folder passed in from the main function
    filenames = glob.glob(f'{message_folder_path}/**/*.csv', recursive=True)

    # Process a batch of 50 files
    for batch in batched(filenames, 50):
        for filename in batch:
            with open(filename, 'r', encoding='utf-8') as fd:
                dict_reader = csv.DictReader(fd)
                for row in dict_reader:
                    # For summary count
                    counts[row['Type']] += 1

                    # Search message for phone numbers. If a phone number or, numbers are located
                    # in the message send those phone numbers to uniqueUsers.
                    phones = get_phone_number(row['Body'])
                    if phones:
                        for phone in phones:
                            if row['Sender']:
                                uniqueUsers.add(f'Date: {row['Date']} Sender: {row["Sender"].strip()}, '
                                                f'phone number in msg: {phone.strip()}')
                            else:
                                uniqueUsers.add(f'Date: {row['Date']} Sender: "None", phone number in msg: '
                                                f'{phone.strip()} ')

                    print(json.dumps({"type": "message", "data": render_csv_messages(row, meta)},
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

    duration = time.time() - start

    summary.append({
        "file": os.path.basename(message_folder_path),
        "time_taken_secs": round(duration, 2),
        "messages": sum(counts.values()),
        "breakdown": dict(counts)
    })


def clean_up_phone_number(phone_number: str) -> str:
    """
    :param phone_number:
    :return: phone_number without +1 or () or - or empty space. e.g. 2395551212
    """
    phone_num = str()
    for char in phone_number:
        if char.isdigit():
            phone_num = phone_num + char
    if phone_num.startswith('1'):
        phone_num = phone_num[1:]
    return phone_num.strip()


def get_contacts_data(dir_path, uniqueUsers: set, uniquePeople: set):
    """
    :param dir_path: passed in from main function
    :param uniqueUsers:  passed in from main function
    :param uniquePeople: passed in from main function
    :descrip: This code processes a txt document in csv format without a header
    """

    # Check to see if the user added the external contacts.txt file to the Synchronoss return folder.
    contents = glob.glob(f'{dir_path}/**/*.txt', recursive=True)

    for file_name in contents:
        if "contacts" in file_name:
            try:
                # Read and parse JSON from text file
                with open(os.path.join(dir_path, file_name), 'rb',) as fd:

                    for record in ijson.items(fd, 'contacts.contact.item'):
                        if firstname := record.get('firstname'):
                            full_name = firstname.replace(' ', '')
                        if lastname := record.get('lastname'):
                            full_name = full_name + ' ' + lastname.replace(' ', '')
                        uniquePeople.add(full_name)

                        if record.get('tel'):
                            for tel in record['tel']:
                                telephone = clean_up_phone_number(tel.get('number'))
                                #re.findall(r'\d{7}', telephone) or re.findall(r'\d{10}', telephone)
                                if len(telephone) == 10:
                                    uniqueUsers.add(f'{full_name} Phone#: {telephone}')
                # File found and processed. Exit the for loop.
                break
            # Grab any exception thrown by pandas. If the contacts document cannot be read do not crash the plugin.
            # Just report the error, whatever it may be.
            except Exception as e:
                logging.error(e)


def get_csv_access_log(dir_path, meta: dict, activities: list, uniqueIPs: set, uniqueDevices: set, uniqueUsers: set):
    """
    :param dir_path: Passed in from main
    :param meta:
    :param activities:
    :param uniqueIPs:
    :param uniqueDevices:
    :param uniqueUsers:
    :return:
    :description: This function process a CSV file
    """

    # Check to see if the user added the external csv device access log file to this return folder
    contents = glob.glob(f'{dir_path}/*.csv', recursive=True)

    for filename in contents:
        with open(filename, 'r', encoding='utf-8') as fd:
            dict_reader = csv.DictReader(fd)
            for batch in batched(dict_reader, 50):
               for row in batch:
                   uniqueDevices.add(row['clientidentifier'])
                   uniqueUsers.add(f'Device: {row["clientidentifier"]}')
                   # For some entries Synchronoss is adding two IPs in this row. The IPs are separated by a
                   # comma. The second IP is a Hosting IP.
                   ipaddress = row['remoteipaddress'].split(',')
                   if len(ipaddress) > 1:
                       for ip in ipaddress:
                           uniqueIPs.add(ip.strip())
                   else:  # There is only one IP Address.
                       uniqueIPs.add(row['remoteipaddress'] if len(ipaddress) == 1 else ipaddress[0])

                   # tag activity
                   activities.append({
                       "type": "data",
                       "dirId": meta['dirId'],
                       "platform": "synchronoss",
                       "date": to_iso_utc(row['server_ts']),
                       "caseId": None,  # the date the messages were sent or received
                       "event": "content uploaded",
                   })
                   # Clean these up.
                   # Synchronoss systems replace missing IPs with a dash character. The client identifier associated with
                   # this missing IP is listed as 'CI' if the hash value for a transmitted file is present in the
                   # 'querystring'. If a hash value is not present Synchronoss places a dash in the client identifier.
               uniqueIPs.discard('-')
               uniqueDevices.discard('CI')
               uniqueDevices.discard('-')


def get_xlsx_access_log(dir_path, meta: dict, activities: list, uniqueIPs: set, uniqueDevices: set, uniqueUsers: set):
    """
    :param dir_path: Passed in from main
    :param meta:
    :param activities:
    :param uniqueIPs:
    :param uniqueDevices:
    :param uniqueUsers:
    :return: Processes a xlsx file
    """

    # Check to see if the user added the external xlsx and contacts.txt file to this return folder
    contents = os.listdir(dir_path)

    for file_name in contents:
        if file_name.endswith('.xlsx'):
            try:
                df = pd.read_excel(os.path.join(dir_path, file_name), engine='openpyxl', engine_kwargs={'read_only': True})
                data_dict = df.to_dict(orient='records')
                # Process 50 data_dict items at a time
                for batch in batched(data_dict, 50):
                    for row in batch:
                        uniqueDevices.add(row['clientidentifier'])
                        # Make the device visible to Paradigm users
                        uniqueUsers.add(f'Device: {row["clientidentifier"]}')
                        # For some entries Synchronoss is adding two IPs in this row. The IPs are separated by a
                        # comma. The second IP is a Hosting IP.
                        ipaddress = row['remoteipaddress'].split(',')
                        if len(ipaddress) > 1:
                            for ip in ipaddress:
                                uniqueIPs.add(ip.strip())
                        else:  # There is only one IP Address.
                            uniqueIPs.add(row['remoteipaddress'] if len(ipaddress) == 1 else ipaddress[0])

                        # tag activity
                        activities.append({
                            "type": "data",
                            "dirId": meta['dirId'],
                            "platform": "synchronoss",
                            "date": to_iso_utc(row['logtimestamp'].replace('[', '').replace(']', ''))
                                    if 'logtimestamp' in row else row['server_ts'],
                            "caseId": None,  # the date the messages were sent or received
                            "event": "content uploaded",
                        })
                    # Clean these up.
                    # Synchronoss systems replace missing IPs with a dash character. The client identifier associated with
                    # this missing IP is listed as 'CI' if the hash value for a transmitted file is present in the
                    # 'querystring'. If a hash value is not present Synchronoss places a dash in the client identifier.
                    uniqueIPs.discard('-')
                    uniqueDevices.discard('CI')
                    uniqueDevices.discard('-')
                    uniqueUsers.discard('Device: -')
            # Grab any exception thrown by pandas. If the Excel document cannot be read do not crash the plugin.
            # Just report the error, whatever it may be.
            except Exception as e:
                logging.error(e)


# Command Line Interface (CLI)
def main(argv: List[str]) -> int:
    """
    :param argv: A list of command line arguments argv[0] = Python script, argv[1] = [run|info], argv[2] = filepath
    :return:
    """
    # Variables to store data collected during processing.
    activities = []
    uniqueUsers = set()
    uniquePeople = set()
    uniqueDevices = set()
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
        # provided in a directory/folder that uses this telephone number as its name. Assuming the user selects this
        # folder as the folder Paradigm will process, capture the directory/folder name. If the user does not select
        # this folder then do not capture the folder name. This will also process an additional xlsx and text file that
        # are not provided in the return folder. If the user adds these two files to the return folder these files will
        # also be processed.
        if re.match(r"^\d{10}", pathlib.Path(dir_path).name):
            uniqueUsers.add(f'Acct phone/number: {pathlib.Path(dir_path).name}')
            # Process the additional xlsx, csv, or text contacts file if the user added them to the return folder.
            # Otherwise, these function will do nothing. The get_xlsx_access_log and get_csv_access_log are laid out
            # exactly the same. Only difference is the format in which they were provided.
            get_xlsx_access_log(dir_path, meta, activities, uniqueIPs, uniqueDevices, uniqueUsers)
            get_csv_access_log(dir_path, meta, activities, uniqueIPs, uniqueDevices, uniqueUsers)
            get_contacts_data(dir_path, uniqueUsers, uniquePeople)

        exclude_dir = ['call', 'VZMOBILE']
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
                    get_text_messages(root_folder, meta, activities)
                # Process all the files in the sms or mms out directory
                if 'out' == pathlib.Path(root_folder).parent.name:
                    get_text_messages(root_folder, meta, activities)
            # Capture new format using CSV files instead of TXT files
            if 'messages' in root_folder:
                get_csv_messages(root_folder, meta, summary, activities, uniqueUsers)

            # Review the files found in each root_folder looking for vCard (Contact Cards) files.
            # Currently, the get_vcard_info() is basic. Need to work on a more robust version.
            for filename in filenames:
                file_path = os.path.join(root_folder, filename)
                if file_path.endswith('.vcf') or file_path.endswith('.x-vCard'):
                    print(f'vCard: {get_vcard_info(file_path, uniqueUsers, uniquePeople, uniqueDevices)}')

        print(json.dumps({"type": "plugin_summary", "data": {
            "company": "Synchronoss",
            "dirId": meta['dirId'],
            "summary": summary,
            "uniqueUsers": list(uniqueUsers),
            "uniqueUserCount": len(uniqueUsers),
            "uniquePeople": list(uniquePeople),
            "uniquePeopleCount": len(uniquePeople),
            "uniqueDeviceIds": list(uniqueDevices),
            "uniqueDeviceCount": len(uniqueDevices),
            "uniqueIPs": list(uniqueIPs),
            "uniqueIPCount": len(uniqueIPs),
            "activities": activities,
            "activityCount": len(activities),
        }}, ensure_ascii=False), flush=True)

    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
