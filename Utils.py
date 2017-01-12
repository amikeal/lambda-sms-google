from __future__ import print_function

import boto3
import json
import re
import decimal
import logging
import requests
from time import strftime as timestamp
from oauth2client.service_account import ServiceAccountCredentials
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

__author__ = "Adam Mikeal <adam@mikeal.org>"
__version__ = "0.01"

log = logging.getLogger()

# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

# Main class to manage customer metadata
class SMSCustomer(object):

    CustomerID = None
    SMSNumber = ""
    GoogleAccount = ""
    SheetID = ""
    RegisteredNumbers = {}
    SplitMethod = ""

    _dynamo = None

    def __init__(self, phone_number):
        self._dynamo = boto3.resource('dynamodb').Table('SMSCustomers')
        self.SMSNumber = phone_number
        self._load_data()

    def __repr__(self):
        return "Customer [ID: {}] on number {}".format(self.CustomerID, self.SMSNumber)

    def _load_data(self):
        '''
            Retrieve all the netadata for the current customer and
            load into the object.
        '''
        try:
            res = self._dynamo.query(
                IndexName='SMSNumber-index',
                KeyConditionExpression=Key('SMSNumber').eq(self.SMSNumber)
            )
        except ClientError as e:
            log.debug("ERROR: " + e.res['Error']['Message'])
        else:
            if res["Count"] != 1:
                log.error("WARNING -- DB query for Twilio number returned more than 1 result!")
            else:
                self.CustomerID = res["Items"][0]["CustomerID"]
                self.GoogleAccount = res["Items"][0]["GoogleAccount"]
                self.SheetID = res["Items"][0]["SheetID"]
                self.RegisteredNumbers = res["Items"][0]["RegisteredNumbers"]
                self.SplitMethod = res["Items"][0]["SplitMethod"]

    def register_number(self, phone_number, student_id, FORCE=False):
        ''' LOGIC:
            1. check all registered IDs for this customer;
            2. if no duplicate exists, append ID-cell# pair to mapping in DB
            3. if the ID already exists, then
                3.1 if ID registered to phone_number, send confirmation mesg
                3.2 if ID registered to a different number, send warning with instructions
                3.3 if FORCE flag is True, delete the current registration and goto #2
        '''

        # check if the ID already exists for this customer
        if student_id in self.RegisteredNumbers.values():
            # what cell number is registered to this ID?
            for cel, sid in self.RegisteredNumbers.iteritems():
                if sid == student_id:
                    already_registered = cel
                    break

            if already_registered == phone_number:
                return_msg = "This student ID ({}) is already registered to this phone number.".format(student_id)
            else:
                # Called with FORCE flag means a UPDATE command. Delete old map, add new one
                if FORCE == True:
                    del self.RegisteredNumbers[cel]
                    self.RegisteredNumbers[phone_number] = student_id
                    self._update_number_map()
                    return_msg = "OK - student ID {} has been updated and is now registered to this phone number.".format(student_id)
                else:
                    return_msg = "This student ID ({}) is currently registered to phone number {}. If you want to move the ID to this new number, text UPDATE &lt;my_ID_here>".format(student_id, cel)

        # this is a new ID, so write it to the DB
        else:
            self.RegisteredNumbers[phone_number] = student_id
            self._update_number_map()
            return_msg = "OK - student ID {} has been registered to this phone number.".format(student_id)

        return {
            'success': True,
            'message': return_msg
        }

    def _update_number_map(self):
        '''
            Updates the map of registered phone numbers / IDs in the DB
        '''
        try:
            res = self._dynamo.update_item(
                Key={
                    'CustomerID': self.CustomerID
                },
                UpdateExpression="set RegisteredNumbers = :l",
                ExpressionAttributeValues={
                    ':l': self.RegisteredNumbers
                },
                ReturnValues="UPDATED_NEW"
            )
        except ClientError as e:
            log.error(e.res['Error']['Message'])
        else:
            if res['ResponseMetadata']['HTTPStatusCode'] == 200:
                return True
            else:
                return False

    def verify_registration(self, phone_number):
        '''
            Verify that the sender is registered to the current customer.
            Returns the student ID for the sender, or None if not found.
        '''
        return self.RegisteredNumbers.get(phone_number)


class GoogleSheet(object):

    SHEET_KEY = ''
    AUTH_SCOPE = ['https://spreadsheets.google.com/feeds']
    AUTH_FILE = 'creds.json'
    API_BASE = 'https://sheets.googleapis.com/v4/spreadsheets'

    _session = None

    def __init__(self, SheetID):
        self.SHEET_KEY = SheetID
        self.authorize_session()

    # Utility function to instantiate auth header for Google API calls
    def authorize_session(self):
        credentials = ServiceAccountCredentials.from_json_keyfile_name(self.AUTH_FILE, scopes=self.AUTH_SCOPE)

        if not credentials.access_token or \
                (hasattr(credentials, 'access_token_expired') and credentials.access_token_expired):
            import httplib2
            credentials.refresh(httplib2.Http())

        session = requests.Session()
        session.headers.update({'Authorization': 'Bearer ' + credentials.access_token})
        self._session = session

    # Utility function to create a named worksheet in a Google Sheet
    def create_worksheet(self, worksheet_name):
        payload = {
            "requests": [
                {"addSheet": {"properties": {"title": worksheet_name}}}
            ]
        }
        log.debug("Fetching list of worksheets...")
        r = self._session.get("{}/{}?&fields=sheets.properties".format(self.API_BASE, self.SHEET_KEY))
        response = json.loads(r.content)
        log.info("Checking for existing worksheet with title: '{}'".format(worksheet_name))
        for d in response['sheets']:
            if d['properties']['title'] == worksheet_name:
                log.debug("Found worksheet... using worksheet for writing")
                return True
            else:
                log.info("Named worksheet not found... creating new worksheet")
                r = self._session.post("{}/{}:batchUpdate".format(self.API_BASE, self.SHEET_KEY), data=json.dumps(payload))
                return True

    # Utility function to parse the message and add a row to a Google Sheet
    def add_row(self, message, extra_fields, split_method='WHITESPACE'):
        log.debug("GoogleSheet.add_row() called with args '{}', '{}', '{}'".format(
            message, extra_fields, split_method))

        # Open a worksheet with a title of today's date
        worksheet_title = timestamp('%Y-%m-%d')
        self.create_worksheet(worksheet_title)

        # Insert the data into the opened worksheet
        if split_method == 'COMMAS':
            split_text = re.split('\s*,\s*', message) # split on commas only
        else:
            split_text = re.split('\W+', message)  # split on any non-word char

        # Combine the elements into the complete field list
        field_list = [timestamp('%Y-%m-%d %H:%M:%S')] + extra_fields + split_text

        log.info("Appending new row to worksheet")
        #max_col = chr(len(split_text) + 70)  # Calculate the letter value for the widest column
        append_url = "{}/{}/values/{}:append?valueInputOption=RAW".format(self.API_BASE, self.SHEET_KEY, worksheet_title)
        append_data = {
            "range": "{}".format(worksheet_title),
            "majorDimension": "ROWS",
            "values": [ field_list, ],
        }
        r = self._session.post(append_url, data=json.dumps(append_data))
        # SHOULD MATCH -- PUT https://sheets.googleapis.com/v4/spreadsheets/{SHEET_KEY}/values/{worksheet_title}:append?valueInputOption=RAW

        if r.status_code == requests.codes.ok:
            log.debug("Appended: {} to Worksheet named {}".format(field_list, worksheet_title))
            return True
        else:
            log.debug("API call returned non-200 status code: {}".format(r.status_code))
            return False
