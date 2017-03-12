from __future__ import print_function

import boto3
import json
import re
import decimal
import logging
import requests
from datetime import datetime as dt
from datetime import timedelta
from oauth2client.service_account import ServiceAccountCredentials
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

__author__ = "Adam Mikeal <adam@mikeal.org>"
__version__ = "0.04"

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
    ResponseMessage = ""
    TimeZoneOffset = 0
    MessageQuota = 0
    LastQuotaUpdate = None
    RecordCreatedOn = None
    RecordUpdatedOn = None

    _db_meta = None
    _db_map = None

    def __init__(self, phone_number, new_record=False):
        self._db_meta = boto3.resource('dynamodb').Table('SMSCustomers')
        self._db_map = boto3.resource('dynamodb').Table('RegisteredNumbers')
        self.SMSNumber = phone_number
        if new_record is False:
            self._load_data()

    def __repr__(self):
        return "Customer [ID: {}] on number {}".format(self.CustomerID, self.SMSNumber)

    @classmethod
    def create(cls, phone_number, email_address):
        # a new costomer object with no data but a phone_number
        new_customer = cls(phone_number, True)
        new_props = {
            'CustomerID': int(phone_number) % 10000000000, # since phone_number is unique, convert to int for ID
            'SMSNumber': phone_number,
            'GoogleAccount': email_address,
            'SplitMethod': 'WHITESPACE',
            'ResponseMessage': 'Submission recorded; {TIMESTAMP}',
            'TimeZoneOffset': -6,
            'MessageQuota': 100,
            'SheetID': '_',
            'LastQuotaUpdate': dt.now().isoformat(),
            'RecordCreatedOn': dt.now().isoformat(),
            'RecordUpdatedOn': ''
        }

        # push basic record to the DB
        try:
            res = new_customer._db_meta.put_item(
                Item = new_props
            )
        except ClientError as e:
            log.error("ERROR: " + e.res['Error']['Message'])
        else:
            if res['ResponseMetadata']['HTTPStatusCode'] == 200:
                for key, val in new_props.items():
                    setattr(new_customer, key, val)
                return new_customer
            else:
                return False

    def get_registered_numbers(self):
        '''
            Fetch the registered numbers for the current CustomerID
        '''
        retval = {}
        try:
            res = self._db_map.query(
                IndexName='RegisteredNumber-index',
                KeyConditionExpression=Key('CustomerID').eq(self.CustomerID)
            )
        except ClientError as e:
            log.error("ERROR: " + e.res['Error']['Message'])
        else:
            if res["ResponseMetadata"]["HTTPStatusCode"] == 200:
                for row in res["Items"]:
                    retval[row["PhoneNumber"]] = row["StudentID"]
                return retval
            else:
                return False

    def _push_data(self):
        '''
            Push all current values from object into the DB
        '''
        pass

    def _load_data(self):
        '''
            Retrieve all the metadata for the current customer and
            load into the object.
        '''
        try:
            res = self._db_meta.query(
                IndexName='SMSNumber-index',
                KeyConditionExpression=Key('SMSNumber').eq(self.SMSNumber)
            )
        except ClientError as e:
            log.error("ERROR: " + e.res['Error']['Message'])
        else:
            if res["Count"] != 1:
                log.error("WARNING -- DB query for Twilio number returned more than 1 result!")
            else:
                for param in [p for p in dir(self) if not p.startswith('_') and not callable(getattr(self,p))]:
                    setattr(self, param, res["Items"][0].get(param))
                self.TimeZoneOffset = int(self.TimeZoneOffset)
                self.RegisteredNumbers = self.get_registered_numbers()

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
            already_registered = self.RegisteredNumbers.keys()[self.RegisteredNumbers.values().index(student_id)]
            # for cel, sid in self.RegisteredNumbers.iteritems():
            #     if sid == student_id:
            #         already_registered = cel
            #         break

            if already_registered == phone_number:
                return_msg = "This student ID ({}) is already registered to this phone number.".format(student_id)
            else:
                # Called with FORCE flag means a UPDATE command. Delete old pairing, add new one
                if FORCE == True:
                    # if the phone_number is registered to another ID, delete that record, too
                    if phone_number in self.RegisteredNumbers:
                        self.remove_registered_number(self.RegisteredNumbers[phone_number])
                    self.remove_registered_number(student_id)
                    self.add_registered_number(phone_number, student_id)
                    return_msg = "OK - student ID {} has been updated and is now registered to this phone number.".format(student_id)
                else:
                    return_msg = "This student ID ({}) is currently registered to another phone number (XXX-X{}). If you want to move the ID to this new number, text UPDATE {}".format(student_id, already_registered[len(already_registered)-3:], student_id)

        # this is a new ID, so write it to the DB
        else:
            # if the phone_number is registered to another ID, delete the record
            if phone_number in self.RegisteredNumbers:
                self.remove_registered_number(self.RegisteredNumbers[phone_number])
            self.add_registered_number(phone_number, student_id)
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
            res = self._db_meta.update_item(
                Key={ 'CustomerID': self.CustomerID },
                UpdateExpression="{} {} {} :val, RecordUpdatedOn = :time".format(update_method, field_name, update_operator),
                ExpressionAttributeValues={ ':val': new_value, ':time': dt.now().isoformat() },
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

    def remove_registered_number(self, student_id):
        '''
            Atomically delete a registered SMS<->ID pair from the DB
        '''
        try:
            res = self._db_map.delete_item(
                Key={
                    'CustomerID': self.CustomerID,
                    'StudentID': student_id
                }
            )
        except ClientError as e:
            log.error(e.response['Error']['Message'])
        else:
            if res['ResponseMetadata']['HTTPStatusCode'] == 200:
                # Remove the student_id from the list contained in the obj
                # TODO eliminate a DB call by editing the object attr directly
                self.RegisteredNumbers = self.get_registered_numbers()
                return True
            else:
                return False

    def add_registered_number(self, phone_number, student_id):
        '''
            Atomically add an SMS<->ID pair to the DB
        '''
        try:
            res = self._db_map.put_item(
                Item={
                    'CustomerID': self.CustomerID,
                    'StudentID': student_id,
                    'PhoneNumber': phone_number,
                    'RecordCreatedOn': dt.now().isoformat()
                }
            )
        except ClientError as e:
            log.error(e.response['Error']['Message'])
        else:
            if res['ResponseMetadata']['HTTPStatusCode'] == 200:
                # Add the SMS<->ID pair to the list contained in the obj
                # TODO eliminate a DB call by editing the object attr directly
                self.RegisteredNumbers = self.get_registered_numbers()
                return True
            else:
                return False

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

    def render_response_message(self, sender_data):
        # TODO Refactor this method to handle bad / no args
        # foo

        # Get current timestamp with TZ offset
        timestamp = dt.now() + timedelta(hours=self.TimeZoneOffset)

        replacements = {
            'TIMESTAMP': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'DATE': timestamp.strftime('%Y-%m-%d'),
            'TIME': timestamp.strftime('%H:%M'),
            'STUDENTID': sender_data[1],
            'SENDER_NUMBER': sender_data[0]
        }
        return self.ResponseMessage.format(**replacements)

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
        log.debug("JSON response: {}".format(repr(response)))
        for d in response['sheets']:
            if d['properties']['title'] == worksheet_name:
                log.debug("Found worksheet... using worksheet for writing")
                return True
        log.info("Named worksheet not found... creating new worksheet")
        r = self._session.post("{}/{}:batchUpdate".format(self.API_BASE, self.SHEET_KEY), data=json.dumps(payload))
        if r.status_code == 200:
            log.debug("JSON Response: {}".format(r.json()))
            return True
        else:
            log.error("ERROR creating new worksheet: HTTP Status {}; JSON: {}".format(r.status_code, r.json()))
            return False

    # Parse the message, build the field list, and add a row to the Google Sheet
    def record_submission(self, message, extra_fields, split_method='WHITESPACE', tz_offset=0):
        log.debug("GoogleSheet.record_submission() called with args '{}', '{}', '{}'".format(
            message, extra_fields, split_method))

        # Get the current date/time with TZ offset
        timestamp = dt.now() + timedelta(hours=int(tz_offset))

        # Set the worksheet title to today's date
        worksheet_title = timestamp.strftime('%Y-%m-%d')

        # Parse the message according to the split_method param
        if split_method == 'COMMAS':
            split_text = re.split('\s*,\s*', message) # split on commas only
        elif split_method == 'SEMICOLONS':
            split_text = re.split('\s*;\s*', message) # split on smicolons only
        else:
            split_text = re.split('\W+', message)  # split on any non-word char

        # Combine the elements (plus a timestamp) into the complete field list
        field_list = [timestamp.strftime('%Y-%m-%d %H:%M:%S')] + extra_fields + split_text

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
            log.debug("Response text: {}".format(r.text))
            return True
        else:
            log.debug("API call returned non-200 status code: {}".format(r.status_code))
            return False

    def copy_sheet(self, template_id, parent_folder=None):
        ''' Copies the sheet identified by template_id and returns a new sheet_id.
            Optionally takes another ID as the parent (containing) folder.
        '''
        pass
