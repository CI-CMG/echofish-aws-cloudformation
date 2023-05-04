#!/usr/bin/env python

import os
import json
import s3fs
import boto3
import logging
import botocore
import aiobotocore
from botocore.config import Config
from botocore.exceptions import ClientError
import numpy as np
import xarray as xr
import pandas as pd

session = boto3.Session()
max_pool_connections = 64

TEMP_OUTPUT_BUCKET = "noaa-wcsd-pds-index"
SECRET_NAME = "NOAA_WCSD_ZARR_PDS_BUCKET"

# aws --profile=echofish --region=us-east-1 secretsmanager get-resource-policy --secret-id="NOAA_WCSD_ZARR_PDS_BUCKET"
ssm_client = boto3.client('ssm')

client_config = botocore.config.Config(max_pool_connections=max_pool_connections)
transfer_config = boto3.s3.transfer.TransferConfig(
    multipart_threshold=8388608 * 2,
    max_concurrency=10,
    multipart_chunksize=8388608 * 2,
    num_download_attempts=5,
    max_io_queue=100,
    io_chunksize=262144,
    use_threads=True,
    max_bandwidth=None
)

s3 = session.client(service_name='s3', config=client_config)  # good
s3_resource = session.resource(service_name='s3')  # bad

WCSD_BUCKET_NAME = 'noaa-wcsd-pds'
WCSD_ZARR_BUCKET_NAME = 'noaa-wcsd-zarr-pds'
OVERWRITE = False  # If True will delete existing Zarr Store
TILE_SIZE = 1024  # TODO: GET FROM UPSTREAM

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_secret(secret_name: str) -> dict:
    # secret_name = "NOAA_WCSD_ZARR_PDS_BUCKET"  # TODO: parameterize
    secretsmanager_client = session.client(service_name='secretsmanager')
    try:
        get_secret_value_response = secretsmanager_client.get_secret_value(SecretId=secret_name)
        return json.loads(get_secret_value_response['SecretString'])
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print("The requested secret " + secret_name + " was not found")
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            print("The request was invalid due to:", e)
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            print("The request had invalid params:", e)
        elif e.response['Error']['Code'] == 'DecryptionFailure':
            print("The requested secret can't be decrypted using the provided KMS key:", e)
        elif e.response['Error']['Code'] == 'InternalServiceError':
            print("An error occurred on service side:", e)


def get_cruise_df() -> pd.DataFrame:
    # Returns df composed of:
    # [ 'PIPELINE_TIME', 'ZARR_BUCKET', 'START_TIME', 'MAX_ECHO_RANGE',
    #  'PIPELINE_STATUS', 'NUM_ECHO_RANGE', 'ZARR_PATH', 'MIN_ECHO_RANGE',
    #  'END_TIME', 'FILENAME', 'NUM_CHANNEL', 'NUM_PING_TIME', 'CHANNELS' ]
    dynamodb = session.resource(service_name='dynamodb')
    ship_name = 'Henry_B._Bigelow'  # TODO: PASS IN
    cruise_name = 'HB0707'  # TODO: PASS IN
    sensor_name = 'EK60'  # TODO: PASS IN
    table_name = f"{ship_name}_{cruise_name}_{sensor_name}"
    table = dynamodb.Table(table_name)
    response = table.scan()  # Scan has 1 MB limit on results --> requires pagination
    data = response['Items']
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        data.extend(response['Items'])
    # df = pd.DataFrame(data)
    return pd.DataFrame(data)


test_file = "D20070712-T033431.raw"  # TODO: UPDATE THIS!!!!

# [0] get dynamoDB table info ####################################
df = get_cruise_df()
start_file_index = df.index[df['FILENAME'] == test_file][0]
start_ping_time_index = int(np.cumsum(df['NUM_PING_TIME'])[start_file_index])

# [1] read cruise level zarr store using xarray for writing ####################################
session = botocore.session.Session()
session = aiobotocore.session.AioSession(profile='echofish')
# s3 = session.client(service_name='s3', config=client_config)  # good
s3 = s3fs.S3FileSystem(session=session)
# s3 = s3fs.S3FileSystem(anon=True)
store = s3fs.S3Map(
    root='s3://noaa-wcsd-pds-index/data/processed/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr',
    s3=s3,
    check=False
)
ds_cruise = xr.open_zarr(store=store, consolidated=True)  # <- cruise level zarr store

# [2] read file level zarr store ####################################
# s3 = s3fs.S3FileSystem(anon=True)
WCSD_ZARR_BUCKET_NAME = 'noaa-wcsd-zarr-pds'
store = s3fs.S3Map(
    root=f's3://{WCSD_ZARR_BUCKET_NAME}/data/raw/Henry_B._Bigelow/HB0707/EK60/{os.path.splitext(os.path.basename(test_file))[0]}.zarr',
    s3=s3,
    check=False
)
ds_file = xr.open_zarr(store=store, consolidated=True)  # <- file level zarr store
# TODO: PROBLEM, ds_file is missing latitude/longitude/timestamp information


# [2] extract gps and time coordinate from file level zarr store ####################################
# use this: https://osoceanacoustics.github.io/echopype-examples/echopype_tour.html


# [3] extract needed variables ####################################

# [4] regrid data array ####################################

# [5] write subset of data to the larger zarr store ####################################


# https://github.com/oftfrfbf/watercolumn/blob/8b7ed605d22f446e1d1f3087971c31b83f1b5f4c/scripts/scan_watercolumn_bucket_by_size.py#L138

total_width_traversed = 0

# TODO: CHANGE BUCKET BACK TO THE ORIGINAL!
WCSD_ZARR_BUCKET_NAME = "noaa-wcsd-pds-index"  # 'noaa-wcsd-zarr-pds'

# read from this zarr store
ship_name = 'Henry_B._Bigelow'
cruise_name = 'HB0707'
sensor_name = 'EK60'
filename = 'D20070711-T182032.zarr'
store_name = os.path.join(WCSD_ZARR_BUCKET_NAME, 'data', 'raw', ship_name, cruise_name, sensor, filename)
store_name = 'noaa-wcsd-zarr-pds/data/raw/Henry_B._Bigelow/HB0707/EK60/D20070711-T182032.zarr'
import fsspec

fs = fsspec.filesystem('s3')
fs.glob(f's3://{store_name}')
ds_temp = xr.open_zarr(store=fsspec.get_mapper(store_name), consolidated=True)

width = ds_temp.data.shape[1]
height = ds_temp.data.shape[0]
start_index = total_width_traversed  # start_index
end_index = total_width_traversed + width  # end_index
print(
    f"width: {width},"
    f"height: {height},"
    f"total_width_traversed: {total_width_traversed},"
    f"s: {start_index}, e: {end_index}"
)
z_resample.latitude[start_index:end_index] = np.round(ds_temp.latitude.values, 5)  # round
z_resample.longitude[start_index:end_index] = np.round(ds_temp.longitude.values, 5)
z_resample.time[start_index:end_index] = ds_temp.time.values.astype(np.int64) / 1e9
total_width_traversed += width
frequencies = ds_temp.frequency.values  # overwriting each time :(
# np.min(ds_temp.range_stop.values) / len(ds_temp.range_bin.values) # 10 cm for AL0502, 50 cm for GU1002,
for freq in range(len(frequencies)):
    for i in range(width):  # 696120
        print(f'{i} of {width} in frequency: {freq}')
        current_data = ds_temp.data.values[:, i, freq]
        current_depth = np.nanmax(ds_temp.range_stop[i])
        # meters_per_pixel = current_depth / 1000 # 2.19
        y = current_data
        x = np.linspace(0, np.ceil(current_depth), num=len(y), endpoint=True)
        f = interp1d(x, y, kind='previous')
        xnew = np.linspace(minimum_resolution, x[-1], num=int(np.ceil(current_depth / minimum_resolution)),
                           endpoint=True)
        ynew = f(xnew)
        ynewHeight = ynew.shape[0]
        # write to zarr w resampled data
        z_resample.data[:ynewHeight, start_index + i, freq] = np.round(ynew, 2)


#### BELOW IS CONSOLIDATED FROM PREVIOUS PROJECT ####


# def handler(event: dict, context: awslambdaric.lambda_context.LambdaContext) -> dict:
def handler(event: dict, context: dict) -> dict:
    try:
        print(f"TEMPDIR: {TEMPDIR}")
        # print(f"Lambda function ARN: {context.invoked_function_arn}")
        # print(f"CloudWatch log stream name: {context.log_stream_name}")
        # print(f"CloudWatch log group name: {context.log_group_name}")
        # print(f"Lambda Request ID: {context.aws_request_id}")
        print(f"echopype version: {ep.__version__}")
        print(f"Lambda function memory limits in MB: {context.memory_limit_in_mb}")
        # TODO: 300000 ms = 300 seconds = 5 minutes, UPDATE!!!
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
        #
        print('calibrating the Sv value')
        # iff os.remove('D20201002-T205446.raw')
        ds_Sv = ep.calibrate.compute_Sv(echodata)
        print(ds_Sv)
        zarr_filename = os.path.join(ship, cruise, sensor, f"{filename}.zarr")
        print(zarr_filename)
        print(f"echopype version: {ep.__version__}")
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
docker build -f Dockerfile -t my-local-lambda:v1 . --no-cache
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
