# https://containers.fan/posts/run-aws-lambda-functions-on-docker/

import os
import time
import boto3
import logging
import tempfile
import echopype as ep
from botocore import UNSIGNED
from botocore.client import Config

s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# TODO: get input bucket, input key
# get output bucket, output key
# output: zarr width: start date, end date
# output: Need min and max depths!

"""
event: type: <class 'dict'>
context: type: <class 'awslambdaric.lambda_context.LambdaContext'>
"""
session = boto3.session.Session()
REGION = my_session.region_name

TEMPDIR = tempfile.gettempdir()
#session = boto3.Session(region_name="us-east-1")  # remove for lambda
dynamodb = session.client('dynamodb')
# table_name = dynamodb.list_tables()['TableNames'][0]
table_name = "echofish-noaa-wcsd-pds"


def writeToDynamoDB(
        key='data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446EEEE.raw',
        cruise="",
        date="",
        size="",
        width=""
):
    # dynamodb = boto3.client('dynamodb')
    #
    session = boto3.Session(region_name="us-east-1")  # remove for lambda
    dynamodb = session.client('dynamodb')
    table_name = dynamodb.list_tables()['TableNames'][0]


status_code = dynamodb.put_item(
    TableName=table_name,
    Item={
        'KEY': {'S': 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446EEEE.raw'},
        'CRUISE': {'S': 'HB20ORTEEE'},
        'DATE': {'S': '2001-01-01T01:01:01ZEEEE'},
        'SIZE': {'N': '22'},
        'WIDTH': {'N': '33'},
    }
)
def readFromDynamoDB()
item = dynamodb.get_item(
    TableName=table_name,
    Key={
        'KEY': {'S': 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446.raw'},
        'CRUISE': {'S': 'HB20ORT'}
    }
)
print(item)


# status_code = dynamodb.put_item(
#     TableName=table_name,
#     Item={
#         'KEY': {'S': 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446BBB.raw'},
#         'CRUISE': {'S': 'HB20ORTBBB'},
#         'DATE': {'S': '2023-04-10T18:43:04Z'},
#         'SIZE': {'N': '123'},
#         'WIDTH': {'N': '456'},
#     }
# )
# status_code = dynamodb.put_item(
#     TableName='echofish-CruiseFiles',
#     Item={
#         'KEY': {'S', 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446CCC.raw'},
#         'CRUISE': {'S': 'HB20ORTCCC'}
#     }
# )
# select_key = dynamodb.get_item(
#     TableName='echofish-CruiseFiles',
#     Key={
#         'KEY': {'S': 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446BBB.raw'},
#         'CRUISE': {'S': 'HB20ORTBBB'},
#     }
# )
# select_key['Item']['WIDTH']
# status_code = dynamodb.put_item(
#     TableName='echofish-CruiseFiles',
#     Item={
#         'KEY': {'S': 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446BBB.raw'},
#         'CRUISE': {'S': 'HB20ORTBBB'},
#         'DATE': {'S': '2023-04-10T18:43:04Z'},
#         'SIZE': {'N': '123'},
#         'WIDTH': {'N': '456'},
#     }
# )


# def handler(event: dict, context: awslambdaric.lambda_context.LambdaContext) -> dict:
def handler(event: dict, context: dict) -> dict:
    try:
        # [1] scan the bucket & dynamodb for all the zarr stores in cruise
        # [2] figure out total width
        # [3] open write connection to s3 pds bucket
        # [4] initialize xarray with all needed values in zarr store
        return {
            "outputBucket": 'foo1',
            "outputKey": filename,
            "outputWidth": ds_Sv.Sv.shape[0],
            "outputHeight": ds_Sv.Sv.shape[2],
            "outputChannels": ds_Sv.Sv.shape[1],
            "outputStartDate": 'foo4',
            "zarr_shape": f"{ds_Sv.Sv.shape}",
        }
    except Exception as err:
        print(f'Encountered exception: {err}')
        logger.error("Exception encountered.")
    finally:
        logger.info("Finishing lambda.")
    #
    return {
        "outputBucket": 'foo1',
        "outputKey": filename,
    }


"""
docker build -f Dockerfile_PYTHON -t my-local-lambda:v1 . --no-cache
#docker run -it -p 8080:8080 my-local-lambda:v1
#docker run -it -p 8080:8080 -m 10000M -e AWS_LAMBDA_FUNCTION_MEMORY_SIZE=10000 my-local-lambda:v1
#docker run -it -p 8080:8080 -m 15000M -e AWS_LAMBDA_FUNCTION_MEMORY_SIZE=15000 my-local-lambda:v1
docker container rm test_lambda; docker run -it -p 8080:8080 -m 15000M -e AWS_LAMBDA_FUNCTION_MEMORY_SIZE=15000 -e AWS_LAMBDA_FUNCTION_TIMEOUT=900 --name test_lambda my-local-lambda:v1
curl -XPOST "http://localhost:8080/2015-03-31/functions/function/invocations" -d '{"payload":"hello world!"}'
curl -XPOST "http://localhost:8080/2015-03-31/functions/function/invocations" -d '{"input_bucket":"noaa-wcsd-pds","input_key":"data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446.raw"}'
AWS_LAMBDA_FUNCTION_VERSION
AWS_LAMBDA_FUNCTION_NAME
AWS_LAMBDA_FUNCTION_MEMORY_SIZE
"""
