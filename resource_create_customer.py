import json
import requests
import logging
import re
from Utils import SMSCustomer, GoogleSheet
from time import strftime as timestamp

# Set a logging level
LOG_LEVEL = logging.DEBUG

# turn down logging level once things are up and running
log = logging.getLogger()
log.setLevel(LOG_LEVEL)


def lambda_handler(event, context):
    '''
        1. Buy new number from VOIP provider (how do we garbage-collect freed numbers?)
        2. create new DB record in DynamoDB
        3. create new folder in Google
            3.1 create new folder using CustomerID/name
            3.2 create new Sheet (from copy) in folder
            3.3 add privs to new Sheet using customer GoogleAccount email
    '''
    pass

    # CLEAN THE INPUTS
    google_email = event["GoogleEmailAddress"]
    area_code = event["RequestedAreaCode"]

    # Get a new number from VOIP API (Twilio, Bandwidth.com, etc)
    import VOIPProvider
    new_number = VOIPProvider.purchase_number(area_code)

    # Make a new Customer object (writes to DB)
    new_customer = SMSCustomer.create(new_number, google_email)

    # Create shared sheet in Google
    #   1. Create new folder
    #   2. Create new sheet in folder
    #   3. Add privs for Customer's Google email
