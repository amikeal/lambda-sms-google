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


def clean_number(cell_number):
    if cell_number[0] == "+":
        return cell_number[1:]

def lambda_handler(event, context):
    log.info("Received event: " + json.dumps(event, indent=2))
    sender_number = clean_number(event["fromNumber"])
    sender_location = event["fromLocation"]
    customer_number = clean_number(event["toNumber"])
    msg_body = event["body"]

    customer = SMSCustomer(customer_number)
    sheet = GoogleSheet(customer.SheetID)

    # Determine if the sender is registering (or updating) an SMS number to an account
    match = re.search("(REGISTER|UPDATE)\W*(\w+)\W*(.*)", msg_body, re.IGNORECASE)
    if match:
        student_id = match.group(2)
        if match.group(1).upper() == 'UPDATE':
            FORCE_FLAG = True
        else:
            FORCE_FLAG = False
        log.debug("Calling register_number() with args '{}', '{}', '{}'".format(student_id, sender_number, customer_number))
        result = customer.register_number(sender_number, student_id, FORCE_FLAG)
        if result['success']:
            return result['message']

    else:
        # First verify that the sender is registered
        student_id = customer.verify_registration(sender_number)
        if not student_id:
            return "Oops - we don't know this number. To use this service, first register with your student ID by texting REGISTER &lt;my_ID_here>"

        # We've confirmed the number is registered, now write the msg into the Google Sheet
        extra_fields = [sender_number, student_id]
        if sheet.record_submission(msg_body, extra_fields, customer.SplitMethod):
            # Return a success message
            return "Submission recorded; {}".format(timestamp('%Y-%m-%d %H:%M:%S'))
        else:
            # Raise an error to pass to Twilio
            return "Ruh roh! Something went wrong; please see your instructor."
