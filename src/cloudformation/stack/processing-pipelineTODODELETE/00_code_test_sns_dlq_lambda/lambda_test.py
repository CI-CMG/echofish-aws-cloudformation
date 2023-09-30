import json
import logging
import os
import time
import random
import boto3
from datetime import datetime


logging.basicConfig(level=logging.DEBUG)
logger=logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def test_out_of_time():
    random_number = random.randint(10, 20)
    logger.info(f"Testing out of time, random_number is: {random_number}")
    time.sleep(random_number)

def test_out_of_memory():
    s = []
    logger.info(f"Testing out of memory")
    for i in range(1000000):
        for j in range(1000000):
            for k in range(1000000):
                s.append("More")

def test_throw_exception():
    try:
        assert (1 > 2), "Assertion failed here."
    except Exception as e:
        logger.info('Exception error in function')
        logger.error(e)
        raise


def lambda_handler(event: dict, context: dict) -> dict:
    logger.info(event)
    #body = json.loads(event['Records'][0]['body'])
    #message = event # json.loads(body["Message"])
    message = json.loads(event['Records'][0]['Sns']['Message'])
    #
    logger.info(message['ship'])
    logger.info(message['cruise'])
    logger.info(message['sensor'])
    logger.info(message['file'])
    #
    #test_out_of_time()
    #test_out_of_memory()
    #
    #try:
    #    assert (1 > 2), "Assertion failed here2."
    #except Exception as e:
    #    logger.info('Exception error2')
    #    logger.error(e)
    #    logger.info('Raise2')
    #    raise
    """
    try:
        test_throw_exception()
    except Exception as e:
        logger.error(e)
        logger.info('Exception was caught')
        return '{ "statusCode": 400, "body": "Echopype failed" }'
    else:
        logger.info('Exception was not caught')
    """
    #test_throw_exception()
    #
    logger.info("Made it past the exception though.")
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S %p")
    message.update(current_time=current_time)
    #
    #sqs = boto3.client('sqs')
    #url = "https://sqs.us-east-1.amazonaws.com/118234403147/rudy-standard-happy-path-test-delete"
    #sqs.send_message(QueueUrl=url, MessageBody=str(message))
    #
    #sns_client = boto3.client('sns')
    #response = sns_client.publish(TopicArn='arn:aws:sns:us-east-1:118234403147:rudy-standard-test-delete', Message=str(message))
    #logger.info(response)
    #
    return {"status": "success123"}
