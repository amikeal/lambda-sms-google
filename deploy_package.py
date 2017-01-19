import os
import zipfile
import sys
import threading

import boto3

ARCHIVE_NAME = 'lambda-package.zip'
S3_BUCKET = 'amikeal-lambda-transfer'
#LAMBDA_FUNCTION = 'ProcessSMSCheckin'
LAMBDA_FUNCTION = 'AcceptAndLogCheckin'


class ProgressPercentage(object):
    def __init__(self, filename):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self._lock = threading.Lock()
    def __call__(self, bytes_amount):
        # To simplify we'll assume this is hooked up
        # to a single filename.
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = (self._seen_so_far / self._size) * 100
            sys.stdout.write(
                "\r%s  %s / %s  (%.2f%%)" % (
                    self._filename, self._seen_so_far, self._size,
                    percentage))
            sys.stdout.flush()

def get_extension(filename):
    basename = os.path.basename(filename)  # os independent
    ext = '.'.join(basename.split('.')[1:])
    return '.' + ext if ext else None

def archive(src, dest, filename):
    output = os.path.join(dest, filename)
    zfh = zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED)

    for root, _, files in os.walk(src):
        for file in files:
            if os.path.basename(file).split('.')[-1] != 'pyc':
                zfh.write(os.path.join(root, file))
    zfh.close()
    return os.path.join(dest, filename)


# if there is an old ZIP file, delete it first
if os.path.exists(ARCHIVE_NAME):
    print("Removing old '{}'...".format(ARCHIVE_NAME))
    os.remove(ARCHIVE_NAME)

# then make the new archive file for uploading
print("Creating new archive '{}'...".format(ARCHIVE_NAME))
new_filename = archive('./', '.', ARCHIVE_NAME)


# upload the new ZIP file into the right bucket
s3 = boto3.client('s3')

# Upload tmp.txt to bucket-name at key-name
s3.upload_file(
    ARCHIVE_NAME, S3_BUCKET, ARCHIVE_NAME,
    Callback=ProgressPercentage(ARCHIVE_NAME))
#
# Available here: https://s3.amazonaws.com/amikeal-lambda-transfer/lambda-package.zip
#

# tell the Lambda service to update the code

lmda = boto3.client('lambda')
print("\n\nUpdating function code in Lambda function '{}' using archive package: {}".format(LAMBDA_FUNCTION, S3_BUCKET+'/'+ARCHIVE_NAME))
response = lmda.update_function_code(
    FunctionName=LAMBDA_FUNCTION,
    S3Bucket=S3_BUCKET,
    S3Key=ARCHIVE_NAME,
    Publish=True
)

if response['ResponseMetadata']['HTTPStatusCode'] == 200:
    print 'SUCCESS'
else:
    from pprint import pprint
    print "ERROR updating Lambda function: \n\n"
    pprint(response)

#
# Command to install libraries in a directory for Lambda access:
#    pip install module-name -t /path/to/project-dir
#
