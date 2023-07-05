#!/usr/bin/env python

import base64
import boto3
from botocore.config import Config
import gzip
import json
import logging
import os
import time, math

from botocore.exceptions import ClientError
#config = Config(region_name='us-west-2', signature_version='v4')
config = Config(signature_version='v4')
#session = boto3.Session(region_name="us-west-2")
session = boto3.Session()
log_client = session.client('logs', config=config)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def logpayload(event):
    logger.setLevel(logging.DEBUG)
    logger.debug(event['awslogs']['data'])
    compressed_payload = base64.b64decode(event['awslogs']['data'])
    uncompressed_payload = gzip.decompress(compressed_payload)
    log_payload = json.loads(uncompressed_payload)
    return log_payload


def error_details(payload):
    error_msg = ""
    log_events = payload['logEvents']
    logger.debug(payload)
    loggroup = payload['logGroup']
    logstream = payload['logStream']
    lambda_func_name = loggroup.split('/')
    logger.debug(f'LogGroup: {loggroup}')
    logger.debug(f'Logstream: {logstream}')
    logger.debug(f'Function name: {lambda_func_name[3]}')
    logger.debug(log_events)
    for log_event in log_events:
        error_msg += log_event['message']
    logger.debug('Message: %s' % error_msg.split("\n")[0])
    # Message: ['2023-03-30T18:33:45.455Z 90403de2-c856-4ab8-9a6f-35be1a7ba5f9 Task timed out after 3.00 seconds', '', '']
    print('-'*10)
    requestId = error_msg.split("\n")[0].split(' ')[1] # "e63712f5-d74c-4975-94de-d5292a96a610"
    logger.debug(f"requestId: {requestId}")
    logger.debug(f"requestId: {type(requestId)}")
    #requestId = "47791332-a8c6-4347-9bea-16570606bc27"
    #logger.debug(f"requestId: {requestId}")
    #logger.debug(f"requestId: {type(requestId)}")
    failed_key = ""
    try:
        time.sleep(60) # Note: CloudWatch Insights needs a lot of time to generate the initial log
        endTime = math.floor(time.time()) + 30
        startTime = endTime - (60 * 60 * 48) # N hours into the past
        response = log_client.start_query(
            logGroupName="/aws/lambda/delete-rudy-error-generating-lambda",
            startTime=startTime,
            endTime=endTime,
            queryString=f"fields @message | filter @requestId like '{requestId}'",
            limit=100
        )
        while True:
            time.sleep(10) # results['status']: Running, Complete
            results = log_client.get_query_results(queryId=response['queryId'])
            logger.debug(f'results temp: {results}')
            if results['status'] == 'Complete':
                break
        searchString = "input key: "
        logger.debug(f"results final: {results['results']}")
        if len(results['results']) > 0:
            for i in results['results']:
                message, _ = i
                if message['value'].find(searchString) > 0:
                    failed_key = message['value'].split('\t')[-1].strip().split(' ')[-1]
                    print(failed_key) # failed key
        else:
            logger.debug("No results returned.")
    except Exception as err:
        logger.error(f"Exception encountered: {err}")
    print('-'*10)
    logger.debug("AAA.")
    return loggroup, logstream, error_msg, lambda_func_name, failed_key


def publish_message(loggroup, logstream, error_msg, lambda_func_name, failed_key):
    logger.debug("CCC.")
    sns_arn = os.environ['SNS_ARN']  # Getting the SNS Topic ARN passed in by the environment variables.
    snsclient = boto3.client('sns')
    try:
        message = ""
        message += "\nLambda Error Summary456" + "\n"
        message += "##########################################################\n"
        message += "# LogGroup Name:- " + str(loggroup) + "\n"
        message += "# LogStream:- " + str(logstream) + "\n"
        message += "# Log Message:- " + "\n"
        message += "# \t\t" + str(error_msg.split("\n")[0]) + "\n"
        message += "# \t\t" + f"failed key: {failed_key}" + "\n"
        message += "##########################################################\n"

        # Sending the notification...
        snsclient.publish(
            TargetArn=sns_arn,
            Subject=f'Execution error for Lambda - {lambda_func_name[3]}',
            Message=message
        )
    except ClientError as e:
        logger.error("An error occured: %s" % e)


def lambda_handler(event: dict, context: dict) -> dict:
    print("Lambda function ARN:", context.invoked_function_arn)
    print("CloudWatch log stream name:", context.log_stream_name)
    print("CloudWatch log group name:",  context.log_group_name)
    print("Lambda Request ID:", context.aws_request_id)
    print("Lambda function memory limits in MB:", context.memory_limit_in_mb)
    print("Lambda time remaining in MS:", context.get_remaining_time_in_millis())
    #
    pload = logpayload(event)
    lgroup, lstream, errmessage, lambdaname, failed_key = error_details(pload)
    logger.debug("BBB.")
    publish_message(lgroup, lstream, errmessage, lambdaname, failed_key)
