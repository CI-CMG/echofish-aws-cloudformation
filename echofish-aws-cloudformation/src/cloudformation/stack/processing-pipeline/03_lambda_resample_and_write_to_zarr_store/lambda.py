#!/usr/bin/env python

import os
import json
import s3fs
import boto3
import logging
import botocore
import aiobotocore
import geopandas
from botocore.config import Config
from botocore.exceptions import ClientError
import numpy as np
import xarray as xr
import pandas as pd
from enum import Enum

ENV = Enum("ENV", ["DEV", "PROD"])

session = boto3.Session()
max_pool_connections = 128
SECRET_NAME = "NOAA_WCSD_ZARR_PDS_BUCKET"
PREFIX = 'rudy'

# WCSD_ZARR_BUCKET_NAME = 'noaa-wcsd-zarr-pds'
INPUT_BUCKET = "noaa-wcsd-pds-index"
OUTPUT_BUCKET = "noaa-wcsd-zarr-pds"

client_config = botocore.config.Config(max_pool_connections=max_pool_connections)
transfer_config = boto3.s3.transfer.TransferConfig(max_concurrency=100)

s3 = session.client(service_name='s3', config=client_config)  # good

OVERWRITE = True  # If True, delete existing Zarr Store
TILE_SIZE = 1024  # TODO: GET FROM UPSTREAM

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

os.environ["HOME"] = "/tmp"
TEMPDIR = os.environ['HOME']


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



def get_table_as_dataframe(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
) -> pd.DataFrame:
    # Only successfully processed files will be aggregated into the larger store
    dynamodb = session.resource(service_name='dynamodb')
    try:
        # if ENV[environment] is ENV.PROD:
        #     table_name = f"{ship_name}_{cruise_name}_{sensor_name}"
        # else:
        #     table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
        table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
        table = dynamodb.Table(table_name)
        response = table.scan()  # Scan has 1 MB limit on results --> paginate
        data = response['Items']
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            data.extend(response['Items'])
    except ClientError as err:
        print('Problem finding the dynamodb table')
        raise err
    df = pd.DataFrame(data)
    df_success = df[df['PIPELINE_STATUS'] == 'SUCCESS']
    if df_success.shape[0] == 0:
        raise
    return df_success


#### BELOW IS CONSOLIDATED FROM PREVIOUS PROJECT ####
def print_diagnostics(context):
    # print(f"TEMPDIR: {TEMPDIR}")
    print(f"Lambda function ARN: {context.invoked_function_arn}")
    print(f"CloudWatch log stream name: {context.log_stream_name}")
    print(f"CloudWatch log group name: {context.log_group_name}")
    print(f"Lambda Request ID: {context.aws_request_id}")
    print(f"Lambda function memory limits in MB: {context.memory_limit_in_mb}")
    print(f"Lambda time remaining in MS: {context.get_remaining_time_in_millis()}")
    print(f"_HANDLER: {os.environ['_HANDLER']}")
    print(f"AWS_EXECUTION_ENV: {os.environ['AWS_EXECUTION_ENV']}")
    # print(f"AWS_LAMBDA_FUNCTION_MEMORY_SIZE: {os.environ['AWS_LAMBDA_FUNCTION_MEMORY_SIZE']}")


# def handler(event: dict, context: awslambdaric.lambda_context.LambdaContext) -> dict:
def main(
    environment: str='DEV',
    prefix: str='rudy',
    ship_name: str='Henry_B._Bigelow',
    cruise_name: str='HB0707',
    sensor_name: str='EK60',
    input_bucket: str=INPUT_BUCKET,
    file_name: str='D20070711-T210709.raw'
) -> None:
    #################################################################
    os.chdir(TEMPDIR)
    if ENV[environment] is ENV.PROD:
        print("PROD, use external credential to write to noaa-wcsd-zarr-pds bucket")
        secret = get_secret(secret_name=SECRET_NAME)
        s3_zarr_client = boto3.client(
            service_name='s3',
            aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
            aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
        )
        s3_zarr_session = boto3.Session(
            aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
            aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
        )
    else:
        print("DEV, use regular credentials to write to dev bucket")
        s3_zarr_client = session.client(service_name='s3', config=client_config)
    #################################################################
    # [0] get dynamoDB table info ####################################
    df = get_table_as_dataframe(
        prefix=prefix,
        ship_name=ship_name,
        cruise_name=cruise_name,
        sensor_name=sensor_name,
    )
    start_file_index = df.index[df['FILE_NAME'] == file_name][0]
    start_ping_time_index = int(np.cumsum(df['NUM_PING_TIME_DROPNA'])[start_file_index])
    #################################################################
    #################################################################
    # [1] read cruise level zarr store using xarray for writing #####
    #session = aiobotocore.session.AioSession(profile='echofish')
    #aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID']
    #aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY']
    session = aiobotocore.session.AioSession.create_client(
        aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
        aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
    )
    s3 = s3fs.S3FileSystem(session=session)
    file_basename = os.path.basename(file_name).split('.')[0]

    geo_json = geopandas.read_file(filename=)
    # TODO: get concave hull with https://pypi.org/project/alphashape/

    s3 = s3fs.S3FileSystem(key=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'], secret=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'])
    store = s3fs.S3Map(
        root=f's3://{INPUT_BUCKET}/data/processed/{ship_name}/{cruise_name}/{sensor_name}/{file_basename}.zarr',
        s3=s3,
        check=False
    )
    ds_cruise = xr.open_zarr(store=store, consolidated=False)  # <- cruise level zarr store


# TODO: PROBLEM HERE IS THAT NO DATA EXISTS AT PATH

# https://github.com/oftfrfbf/watercolumn/blob/master/scripts/zarr_upsample.py
#
#
#
#
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
store_name = os.path.join(WCSD_ZARR_BUCKET_NAME, 'data', 'raw', ship_name, cruise_name, sensor_name, filename)
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


#
#
try:
    if os.path.exists(os.path.join("tmp", filename)):
        os.remove(os.path.join("tmp", filename))
    print(f"Lambda time remaining in MS: {context.get_remaining_time_in_millis()}")
    # TODO: clean up before processing next files
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

def lambda_handler(event: dict, context: dict) -> dict:
    print_diagnostics(context)
    main(
        environment=os.environ['ENV'],  # DEV or TEST
        prefix=os.environ['PREFIX'],    # unique to each cloudformation deployment
        ship_name=os.environ['SHIP'],
        cruise_name=os.environ['CRUISE'],
        sensor_name=os.environ['SENSOR'],
        file_name=os.environ['FILE']
    )

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

# 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20201002-T205446.raw',  # larger file 1GB
# 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20200226-T001537.raw',  # medium file 100MB
# 'data/raw/Henry_B._Bigelow/HB20ORT/EK60/D20200225-T163738.raw',  # smaller file 64MB
