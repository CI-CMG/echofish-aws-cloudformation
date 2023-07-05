# https://containers.fan/posts/run-aws-lambda-functions-on-docker/

import os
import time
# import awslambdaric.lambda_context
import boto3
import logging
import tempfile
import numpy as np
import echopype as ep
from botocore import UNSIGNED
from botocore.client import Config

s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

my_session = boto3.session.Session()
my_region = my_session.region_name

TEMPDIR = tempfile.gettempdir()
session = boto3.Session(region_name="us-east-1")  # remove for lambda
session = boto3.Session(profile_name="echofish", region_name="us-east-1")  # remove for lambda
dynamodb = session.client('dynamodb')
# table_name = dynamodb.list_tables()['TableNames'] # [0]
table_name = "echofish-noaa-wcsd-pds"


def writeToDynamoDB(
    table_name="echofish-noaa-wcsd-pds"
    key='data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446EEEE.raw',
    cruise="HB20ORT",
    size="",
    width=""
):
# dynamodb = boto3.client('dynamodb')
session = boto3.Session(profile_name="echofish", region_name="us-east-1")  # remove for lambda
dynamodb = session.client('dynamodb')
table_name = 'echofish-noaa-wcsd-pds' # dynamodb.list_tables()['TableNames'][0]
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

def readFromDynamoDB(
    table_name="echofish-noaa-wcsd-pds"
    key='data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446EEEE.raw',
    cruise="HB20ORT"
):
item = dynamodb.get_item(
    TableName=table_name,
    Key={
        'KEY': {'S': },
        'CRUISE': {'S': cruise}
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
        print(f"TEMPDIR: {TEMPDIR}")
        print(f"Lambda function ARN: {context.invoked_function_arn}")
        print(f"CloudWatch log stream name: {context.log_stream_name}")
        print(f"CloudWatch log group name: {context.log_group_name}")
        print(f"Lambda Request ID: {context.aws_request_id}")
        print(f"echopype version: {ep.__version__}")
        print(f"Lambda function memory limits in MB: {context.memory_limit_in_mb}")
        print(f"Lambda time remaining in MS: {context.get_remaining_time_in_millis()}")
        #
        print(f"_HANDLER: {os.environ['_HANDLER']}")
        print(f"AWS_EXECUTION_ENV: {os.environ['AWS_EXECUTION_ENV']}")
        # print(f"AWS_LAMBDA_FUNCTION_MEMORY_SIZE: {os.environ['AWS_LAMBDA_FUNCTION_MEMORY_SIZE']}")
        #
        input_bucket = event["input_bucket"]  # 'noaa-wcsd-pds'
        print(f"input bucket: {input_bucket}")
        input_key = event["input_key"]  # 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20200225-T163738.raw'
        print(f"input key: {input_key}")
        output_bucket = event["output_bucket"]  # 'noaa-wcsd-zarr-pds'
        print(f"output bucket: {output_bucket}")
        output_key = event["output_key"]
        print(f"output key: {output_key}")  # data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20200225-T163738.zarr
        # raw_file = '/tmp/D20201002-T205446.raw'
        row_split = input_key.split(os.sep)
        ship, cruise, sensor, filename = row_split[-4:]  # 'Okeanos_Explorer', 'EX1608', 'EK60'
        print(f"filename: {filename}")
        raw_file = os.path.join(TEMPDIR, filename)
        print(f"raw_file: {raw_file}")
        print(row_split)
        # TODO: check if file size is too small
        #  Note: there is a 512 MB size limit for /tmp directory
        # 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446.raw',  # larger file 1GB
        # 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20200226-T001537.raw',  # medium file 100MB
        # 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20200225-T163738.raw',  # smaller file 64MB
        print(f"Bucket={input_bucket}, Key={input_key}, Filename={raw_file}")
        s3.download_file(Bucket=input_bucket, Key=input_key, Filename=raw_file)
        # TODO: is this using tmp directory, use "tempfile"
        # TODO: limit to % of actual available
        ### CRASHING HERE...
        echodata = ep.open_raw(raw_file, sonar_model='EK60')  # , use_swap=True, max_mb=8000)
        print(echodata)
        calibrated = True
        if echodata.sonar.beam_group_descr.values[0].find('uncalibrated') > 0:
            calibrated = False
        #
        print('calibrating the Sv value')
        # iff os.remove('D20201002-T205446.raw')
        ds_Sv = ep.calibrate.compute_Sv(echodata)
        print(ds_Sv)
        width = len(ds_Sv.Sv.ping_time)
        for i in range(len(ds_Sv.Sv.ping_time)):
            # check to see which indices have data
            #ds_Sv.Sv.values[:, i, :].shape
            print( np.nanmax(ds_Sv.Sv.values[:, i, :]) )
            if np.isnan( ds_Sv.Sv.values[:, i, :] ).all(): # checks to see if any are nan
                print(i)
        #
        # calculates the width
        #
        zarr_filename = os.path.join(ship, cruise, sensor, f"{filename}.zarr")
        print(zarr_filename)
        # if os.path.exists(zarr_filename): #    os.remove(zarr_filename)
        ds_Sv.to_zarr(store=zarr_filename)
        #
        ### get zarr statistics and return the Sv width
        #
        # TODO: Clean up, Delete raw file
        if os.path.exists(os.path.join("tmp", filename)):
            os.remove(os.path.join("tmp", filename))
        print(f"Lambda time remaining in MS: {context.get_remaining_time_in_millis()}")
        # TODO: clean up before processing next files
        return {
            "outputBucket": 'foo1',
            "outputKey": filename,
            "outputWidth": ds_Sv.Sv.shape[0],
            "outputHeight": ds_Sv.Sv.shape[2],
            "outputChannels": ds_Sv.Sv.shape[1],
            "outputStartDate": 'foo4',
            "zarr_shape": f"{ds_Sv.Sv.shape}",
            "min_depth": min_depth, # will need these for the new gridded data
            "max_depth": max_depth,
            "total_width": total_width,
        }
    except Exception as err:
        print(f'Encountered exception: {err}')
        logger.error("Exception encountered.")
    finally:
        logger.info("Finishing lambda.")
    #
    print("________________________________")
    return {
        "outputBucket": 'foo1',
        "outputKey": filename,
        # "outputWidth": ds_Sv.Sv.shape[0],
        # "outputHeight": ds_Sv.Sv.shape[2],
        # "outputChannels": ds_Sv.Sv.shape[1],
        # "outputStartDate": 'foo4',
        # "zarr_shape": f"{ds_Sv.Sv.shape}",
    }


# logger.info("This is a sample INFO message.. !!")
# logger.debug("This is a sample DEBUG message.. !!")
# logger.error("This is a sample ERROR message.... !!")
# logger.critical("This is a sample 6xx error message.. !!")

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
