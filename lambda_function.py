import json
import requests
import logging
import re
import decimal
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


# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

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
def addrow(customer_number, student_id, sender, location, text):

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
    field_list = [timestamp('%Y-%m-%d %H:%M:%S'), sender, location, student_id] + split_text
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

def register_number(student_id):
    return "OK - student ID {} has been registered to this phone number.".format(student_id)

def verify_registration(cell_number, customer_number):
    ''' For the current customer (toNumber in Twilio), query for the metadata
        and retrieve all registered student_ids. Return the ID for the sending
        number (fromNumber in Twilio), or 'None' if not yet registered.
    '''
    import boto3
    from boto3.dynamodb.conditions import Key
    from botocore.exceptions import ClientError
    dynamo = boto3.resource('dynamodb').Table('SMSCustomers')
    try:
        response = dynamo.query(
            IndexName='SMSNumber-index',
            KeyConditionExpression=Key('SMSNumber').eq(customer_number)
        )
    except ClientError as e:
        print("ERROR: " + e.response['Error']['Message'])
    else:
        numbers_map = response['Items'][0]['RegisteredNumbers']
        return numbers_map.get(cell_number)
        #return "This phone number has been registered with the ID {}".format(student_id)

def clean_number(cell_number):
    if cell_number[0] == "+":
        return cell_number[1:]

def lambda_handler(event, context):
    log.info("Received event: " + json.dumps(event, indent=2))
    sender_number = clean_number(event["fromNumber"])
    sender_location = event["fromLocation"]
    customer_number = clean_number(event["toNumber"])
    msg_body = event["body"]

    # Determine if the sender is registering an SMS number to an account
    match = re.search("REGISTER (\S+)", msg_body, re.IGNORECASE)
    if match:
        student_id = match.group(1)
        log.debug("Calling register_number() with arg '{}'".format(student_id))
        register_number(student_id)

    else:
        # First verify that the sender is registered
        student_id = verify_registration(sender_number, customer_number)
        if not student_id:
            return "Oops - we don't know this number. To use this service, \
                    first register with your student ID by texting REGISTER &lt;my_ID_here>"

        # We've confirmed the number is registered, so go ahead and write the msg into Google Sheets
        if addrow(customer_number, student_id, sender_number, sender_location, msg_body):
            log.debug("Calling addrow() with args '{}', '{}', '{}', '{}', '{}'".format(
                customer_number, student_id, sender_number, sender_location, msg_body))
            # Return a success message
            return "Attendence checkin recorded; {}".format(timestamp('%Y-%m-%d %H:%M:%S'))
        else:
            # Raise an error to pass to Twilio
            log.error("ERROR calling addrow()...")
            return "Oh, snap! Something went wrong; please see your instructor."
