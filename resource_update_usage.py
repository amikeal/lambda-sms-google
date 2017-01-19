import json
import requests
import logging
import re
from Utils import SMSCustomer, GoogleSheet
from time import strftime as timestamp
from oauth2client.service_account import ServiceAccountCredentials

# Set a logging level
LOG_LEVEL = logging.DEBUG

# turn down logging level once things are up and running
log = logging.getLogger()
log.setLevel(LOG_LEVEL)


def lambda_handler(event, context):
    '''
        EVENT PARAMS:
            {
                CustomerID, PhoneNumber, current_message_quota, last_update
            }
        1. For the given phone number, query the VOIP API for the number
           of messages sent since last_update (message_count)
        2. For the given CustomerID, update the MessageQuota value in
           DynamoDB to be [current_message_quota - message_count]
    '''
    pass

def get_recent_messages(phone_number, last_update):
    '''
        For the given phone number, query the VOIP API for the
        number of messages sent since last_update
    '''
    pass

def queue_quota_checks():
    '''

        1. Query DB for all valid Customers
        2. For each CustomerID, make a HTTP call to /update_usage
    '''
    pass
