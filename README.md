lambda-sms-google
=================

Decsription
-----------

Experimental project to push data into a Google Sheet from an SMS message via Twilio.


Overview
--------

This experiment is the result of a need to quickly gather data from SMS messages
into an easy-to-manage and easy-to-share data source. Also because I wanted to play
with AWS Lambda.

The flow happens like this:

1. User sends and SMS message to a Twilio number
2. Twilio receieves the SMS, and calls a webhook with the body of the message (and other Twilio metadata)
3. The webhook address is a REST API defined by AWS API Gateway
4. API Gateway takes the incoming Twilio request and converts the data into a JSON payload consumable by an AWS Lambda process
5. The Lambda process is triggered by the API Gateway request, and executes the Python function inside `lambda_function.py`
6. The Python function parses the data from Twilio (including the SMS message body), and writes the data into a Google Sheet (opened using credentials generated from the Google Sheets API)
7. If the write is successful, Lambda returns a `SUCCESS` response to the API Gateway
8. The API Gateway takes the response, and builds a valid Twilio response based on success or failure
9. This response is sent back to Twilio as an XML payload (using TwiML)
10. Twilio sends a response back to the cell number
