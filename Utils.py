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
__version__ = "0.02"

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
    MessageQuota = 0
    LastQuotaUpdate = None

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
                # [a for a in dir(f) if not a.startswith('__') and not callable(getattr(f,a))]
                self.CustomerID = res["Items"][0]["CustomerID"]
                self.GoogleAccount = res["Items"][0]["GoogleAccount"]
                self.SheetID = res["Items"][0]["SheetID"]
                self.RegisteredNumbers = res["Items"][0]["RegisteredNumbers"]
                self.SplitMethod = res["Items"][0]["SplitMethod"]
                self.MessageQuota = res["Items"][0]["MessageQuota"]
                self.LastQuotaUpdate = res["Items"][0]["LastQuotaUpdate"]

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
                    return_msg = "This student ID ({}) is currently registered to another phone number (XXX-X{}). If you want to move the ID to this new number, text UPDATE {}".format(student_id, cel[len(cel)-3:], student_id)

        # this is a new ID, so write it to the DB
        else:
            self.RegisteredNumbers[phone_number] = student_id
            self._update_number_map()
            return_msg = "OK - student ID {} has been registered to this phone number.".format(student_id)

        return {
            'success': True,
            'message': return_msg
        }

    def  _update_field_value(self, field_name, field_value=None, update_method='SET'):
        '''
            For a given field name, updates the DynamoDB record
            with the current value in the object
        '''
        if update_method not in ('SET', 'ADD'):
            log.error("ERROR: update method must be one of 'SET' or 'ADD'")
            return False

        # If we were passed a field_value, the it overrides the current instance attribute
        if field_value is not None:
            new_value = field_value
        else:
            new_value = getattr(self, field_name)

        if update_method == 'ADD':
            # the UpdateExpression for ADD doesn't have an operator
            update_operator = ''
            # check to see if we were passed a number or a string
            if isinstance(getattr(self, field_name), (int, float)) is False:
                # attempt to coerce the value into a number
                try:
                    new_value = int(new_value)
                except ValueError:
                    # Int didn't work; let's try float
                    try:
                        new_value = int(new_value)
                    except ValueError:
                        # if unable to make a number, then we cannot use the ADD method
                        return False
        else:
            # else we are using SET method so we need an '='
            update_operator = '='

        try:
            res = self._dynamo.update_item(
                Key={
                    'CustomerID': self.CustomerID
                },
                UpdateExpression="{} {} {} :val".format(update_method, field_name, update_operator),
                ExpressionAttributeValues={
                    ':val': new_value
                },
                ReturnValues="UPDATED_NEW"
            )
        except ClientError as e:
            log.error(e.response['Error']['Message'])
        else:
            if res['ResponseMetadata']['HTTPStatusCode'] == 200:
                # Update the attr in the object to match the DB
                setattr(self, field_name, res['Attributes'][field_name])
                return True
            else:
                return False

    def _update_number_map(self):
        '''
            Updates the map of registered phone numbers / IDs in the DB
        '''
        return self._update_field_value("RegisteredNumbers")

    def decrement_message_quota(self, message_count):
        '''
            Decrements the MessageQuota field in the DB record by the given value
        '''
        if message_count > 0:
            message_count *= -1

        return self._update_field_value('MessageQuota', message_count, 'ADD')

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

    # Parse the message, build the field list, and add a row to the Google Sheet
    def record_submission(self, message, extra_fields, split_method='WHITESPACE'):
        log.debug("GoogleSheet.record_submission() called with args '{}', '{}', '{}'".format(
            message, extra_fields, split_method))

        # Set the worksheet title to today's date
        worksheet_title = timestamp('%Y-%m-%d')

        # Parse the message according to the split_method param
        if split_method == 'COMMAS':
            split_text = re.split('\s*,\s*', message) # split on commas only
        else:
            split_text = re.split('\W+', message)  # split on any non-word char

        # Combine the elements (plus a timestamp) into the complete field list
        field_list = [timestamp('%Y-%m-%d %H:%M:%S')] + extra_fields + split_text

        # Call the add_row() method with the assembled arguments
        return self.add_row(worksheet_title, field_list)

    # Utility function to add a row to a specified worksheet in the Google Sheet
    def add_row(self, worksheet_title, field_list):
        log.debug("GoogleSheet.add_row() called with args '{}', '{}'".format(worksheet_title, field_list))

        # Ensure a worksheet with the correct title exists
        self.create_worksheet(worksheet_title)

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

    def copy_sheet(self, template_id, parent_folder=None):
        ''' Copies the sheet identified by template_id and returns a new sheet_id.
            Optionally takes another ID as the parent (containing) folder.
        '''
        pass
