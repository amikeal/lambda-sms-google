import json
import requests
from time import strftime as timestamp
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# Setup access to Google sheets
scopes = ['https://spreadsheets.google.com/feeds']
credentials = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scopes=scopes)

def log(msg):
    print(timestamp('%H:%M:%S'), ": ", msg)

def addrow(sender, text):
    gc = gspread.authorize(credentials)
    sheet = gc.open_by_key('1bGpMTkkInMjrupVQouydb2WZDH7c2jeIOtlcYbgOC6g')
    log("Opening default worksheet 'INBOX'")
    worksheet = sheet.worksheet("INBOX")
    # Check to see if a worksheet for today's date exists; if not, create it
    log("Fetching list of worksheets...")
    worksheet_list = sheet.worksheets()
    worksheet_names = [w.title for w in worksheet_list]
    date_name = timestamp('%Y-%m-%d')
    log("Checking for existing worksheet with title: %s" % (date_name))
    if date_name not in worksheet_names:
        log("Named worksheet not found... creating worksheet")
        worksheet = sheet.add_worksheet(title=date_name, rows="1", cols="20")
    else:
        log("Found workshet... opening worksheet for writing")
        worksheet = sheet.worksheet(date_name)
    # Insert the data into the opened worksheet
    field_list = [timestamp('%Y-%m-%d %H:%M:%S'), sender, text]
    log("Appending new row to worksheet")
    worksheet.append_row(field_list)
    log("Appended: %s to Worksheet named %s" % (field_list, worksheet.title))
    return True

def lambda_handler(event, context):
    # turn off logging once things are up and running
    log("Received event: " + json.dumps(event, indent=2))
    sender = event["fromNumber"]
    msg_body = event["body"]
    if addrow(sender, msg_body):
        # Return a success message
        return 'SUCCESS'
    else:
        # Raise an error to pass to Twilio
        raise Exception('ERROR')
