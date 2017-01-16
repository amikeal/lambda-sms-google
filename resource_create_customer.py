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
        1. create new DB record in DynamoDB
        2. create new folder in Google
            2.1 create new folder using CustomerID/name
            2.2 create new Sheet (from copy) in folder
            2.3 add privs to new Sheet using customer GoogleAccount email
    '''
    pass
