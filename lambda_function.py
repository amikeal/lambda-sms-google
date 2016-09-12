import json
import requests
import logging
from time import strftime as timestamp
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# Set a logging level
LOG_LEVEL = logging.DEBUG

# turn down logging level once things are up and running
log = logging.getLogger()
log.setLevel(LOG_LEVEL)

# Setup access to Google sheets
scopes = ['https://spreadsheets.google.com/feeds']
credentials = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scopes=scopes)

# Utility function to parse the message and add a row to a Google Sheet
def addrow(sender, location, text):
    gc = gspread.authorize(credentials)
    sheet = gc.open_by_key('1bGpMTkkInMjrupVQouydb2WZDH7c2jeIOtlcYbgOC6g')
    log.info("Opening default worksheet 'INBOX'")
    worksheet = sheet.worksheet("INBOX")
    # Check to see if a worksheet for today's date exists; if not, create it
    log.info("Fetching list of worksheets...")
    worksheet_list = sheet.worksheets()
    worksheet_names = [w.title for w in worksheet_list]
    date_name = timestamp('%Y-%m-%d')
    log.info("Checking for existing worksheet with title: {}".format(date_name))
    if date_name not in worksheet_names:
        log.info("Named worksheet not found... creating worksheet")
        worksheet = sheet.add_worksheet(title=date_name, rows="1", cols="20")
    else:
        log.info("Found workshet... opening worksheet for writing")
        worksheet = sheet.worksheet(date_name)
    # Insert the data into the opened worksheet
    field_list = [timestamp('%Y-%m-%d %H:%M:%S'), sender, location] + [x.strip() for x in text.split(',')]
    log.info("Appending new row to worksheet (calling gspread.append_row()... )")
    worksheet.append_row(field_list)
    log.info("Appended: {} to Worksheet named {}".format(field_list, worksheet.title))
    return True

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
