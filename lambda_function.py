import json
import requests
from time import strftime as timestamp
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# Setup access to Google sheets
scopes = ['https://spreadsheets.google.com/feeds']
credentials = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scopes=scopes)

def addrow(sender, text):
    gc = gspread.authorize(credentials)
    sheet = gc.open_by_key('1bGpMTkkInMjrupVQouydb2WZDH7c2jeIOtlcYbgOC6g')
    worksheet = sheet.worksheet("INBOX")
    # Check to see if a worksheet for today's date exists; if not, create it
    worksheet_list = sheet.worksheets()
    worksheet_names = [w.title for w in worksheet_list]
    date_name = timestamp('%Y-%m-%d')
    if date_name not in worksheet_names:
        worksheet = sheet.add_worksheet(title=date_name, rows="100", cols="20")
    else:
        worksheet = sheet.worksheet(date_name)
    # Insert the data into the opened worksheet
    field_list = [timestamp('%Y-%m-%d %H:%M:%S'), sender, text]
    worksheet.insert_row(field_list, index=1)
    print "Appended: ", field_list, " to Worksheet named ", worksheet.title
    return True

def lambda_handler(event, context):
    # turn off logging once things are up and running
    print("Received event: " + json.dumps(event, indent=2))
    sender = event["fromNumber"]
    msg_body = event["body"]
    if addrow(sender, msg_body):
        # Return a success message
        return 'SUCCESS'
    else:
        # Raise an error to pass to Twilio
        raise Exception('ERROR')
