import json
import requests
import logging
import re
from time import strftime as timestamp
from oauth2client.service_account import ServiceAccountCredentials

# Key for the Google Sheet to write to
SHEET_KEY = '1bGpMTkkInMjrupVQouydb2WZDH7c2jeIOtlcYbgOC6g'
AUTH_SCOPE = ['https://spreadsheets.google.com/feeds']
AUTH_FILE = 'creds.json'
API_BASE = 'https://sheets.googleapis.com/v4/spreadsheets'

# Text parsing options
SPLIT_AGGRESIVE = False

# Set a logging level
LOG_LEVEL = logging.DEBUG

# turn down logging level once things are up and running
log = logging.getLogger()
log.setLevel(LOG_LEVEL)


# Utility function to create a named worksheet in the current Sheet
def create_worksheet(http_session, worksheet_name):
    payload = {
        "requests": [
            {"addSheet": {"properties": {"title": worksheet_name}}}
        ]
    }

    log.debug("Fetching list of worksheets...")
    r = http_session.get("{}/{}?&fields=sheets.properties".format(API_BASE, SHEET_KEY))
    response = json.loads(r.content)

    log.info("Checking for existing worksheet with title: '{}'".format(worksheet_name))
    for d in response['sheets']:
        if d['properties']['title'] == worksheet_name:
            log.debug("Found worksheet... using worksheet for writing")
            return True
        else:
            log.info("Named worksheet not found... creating new worksheet")
            r = http_session.post("{}/{}:batchUpdate".format(API_BASE, SHEET_KEY), data=json.dumps(payload))
            return True


# Utility function to instantiate auth header
def authorize_session():
    credentials = ServiceAccountCredentials.from_json_keyfile_name(AUTH_FILE, scopes=AUTH_SCOPE)

    if not credentials.access_token or \
            (hasattr(credentials, 'access_token_expired') and credentials.access_token_expired):
        import httplib2
        credentials.refresh(httplib2.Http())

    session = requests.Session()
    session.headers.update({'Authorization': 'Bearer ' + credentials.access_token})
    return session

# Utility function to parse the message and add a row to a Google Sheet
def addrow(sender, location, text):

    # Authorize to the Google Sheet
    http_session = authorize_session()

    # Open a worksheet with a title of today's date
    worksheet_title = timestamp('%Y-%m-%d')
    create_worksheet(http_session, worksheet_title)

    # Insert the data into the opened worksheet
    #split_text = [x.strip() for x in text.split(',')]
    if SPLIT_AGGRESIVE:
        split_text = re.split('\s*,\s*', text) # split on commas only
    else:
        split_text = re.split('\W+', text)  # split on any non-word char
    field_list = [timestamp('%Y-%m-%d %H:%M:%S'), sender, location] + split_text
    log.info("Appending new row to worksheet")
    #max_col = chr(len(split_text) + 70)  # Calculate the letter value for the widest column
    append_url = "{}/{}/values/{}:append?valueInputOption=RAW".format(API_BASE, SHEET_KEY, worksheet_title)
    append_data = {
        "range": "{}".format(worksheet_title),
        "majorDimension": "ROWS",
        "values": [ field_list, ],
    }
    r = http_session.post(append_url, data=json.dumps(append_data))
    # SHOULD MATCH -- PUT https://sheets.googleapis.com/v4/spreadsheets/{SHEET_KEY}/values/{worksheet_title}:append?valueInputOption=RAW
    if r.status_code == requests.codes.ok:
        log.debug("Appended: {} to Worksheet named {}".format(field_list, worksheet_title))
        return True
    else:
        return False


def lambda_handler(event, context):
    log.info("Received event: " + json.dumps(event, indent=2))
    sender = event["fromNumber"]
    location = event["fromLocation"]
    msg_body = event["body"]
    log.debug("Calling addrow() with args '{}, '{}', '{}'".format(sender, location, msg_body))

    # TODO:  Change to try-catch block?
    if addrow(sender, location, msg_body):
        # Return a success message
        return 'SUCCESS'
    else:
        # Raise an error to pass to Twilio
        log.error("Caught exception from addrow()...")
        raise Exception('ERROR')
