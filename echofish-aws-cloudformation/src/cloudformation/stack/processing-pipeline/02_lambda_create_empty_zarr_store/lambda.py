#!/usr/bin/env python

import os
import json
import boto3
import shutil
import botocore
from botocore.config import Config
from botocore.exceptions import ClientError
import numpy as np
from numcodecs import Blosc
import zarr
import pandas as pd
from enum import Enum

ENV = Enum("ENV", ["DEV", "PROD"])

# aws --profile=echofish --region=us-east-1 secretsmanager get-resource-policy --secret-id="NOAA_WCSD_ZARR_PDS_BUCKET"
# client = boto3.client('ssm')

session = boto3.Session()
max_pool_connections = 64
SECRET_NAME = "NOAA_WCSD_ZARR_PDS_BUCKET"
PREFIX = 'RUDY'

client_config = botocore.config.Config(max_pool_connections=max_pool_connections)
transfer_config = boto3.s3.transfer.TransferConfig(
    multipart_threshold=8388608 * 2,
    max_concurrency=100,
    multipart_chunksize=8388608 * 2,
    num_download_attempts=5,
    max_io_queue=100,
    io_chunksize=262144,
    use_threads=True,
    max_bandwidth=None
)

s3 = session.client(service_name='s3', config=client_config)  # good
#s3_resource = session.resource(service_name='s3')  # bad

WCSD_BUCKET_NAME = 'noaa-wcsd-pds'
OVERWRITE = True  # If True will delete existing Zarr Store
TILE_SIZE = 1024

def upload_files(
        local_directory: str,
        bucket: str,
        object_prefix: str,
        s3_client
) -> None:
    # Note: the files are being uploaded to a third party bucket where
    # the credentials should be saved in the aws secrets manager.
    for subdir, dirs, files in os.walk(local_directory):
        for file in files:
            local_path = os.path.join(subdir, file)
            print(local_path)
            s3_key = os.path.join(object_prefix, local_path)
            try:
                s3_client.upload_file(
                    Filename=local_path,
                    Bucket=bucket,
                    Key=s3_key,
                    Config=transfer_config
                )
            except ClientError as e:
                # logging.error(e)
                print(e)


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


def find_child_objects(bucket_name: str, sub_prefix: str) -> list:
    # Find all objects for a given prefix string.
    # Returns list of strings.
    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=sub_prefix)
    objects = []
    for page in page_iterator:
        objects.extend(page['Contents'])
    return objects


def get_raw_files(bucket_name: str, sub_prefix: str, file_suffix: str = None) -> list:
    # Get all children files. Optionally defined by file_suffix.
    # Returns empty list if none are found or error encountered.
    print('Getting raw files')
    raw_files = []
    try:
        children = find_child_objects(bucket_name=bucket_name, sub_prefix=sub_prefix)
        if file_suffix is None:
            raw_files = children
        else:
            for i in children:
                # Note any files with predicate 'NOISE' are to be ignored, see: "Bell_M._Shimada/SH1507"
                if i['Key'].endswith(file_suffix) and not os.path.basename(i['Key']).startswith('NOISE'):
                    raw_files.append(i['Key'])
            return raw_files
    except:
        print("Some problem was encountered.")
    finally:
        return raw_files


def create_zarr_store(
        store_name: str,
        width: int,
        height: int,
        min_echo_range: float,
        channel: list,
        frequency: list,
) -> None:
    # Creates an empty Zarr store
    compressor = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
    store = zarr.DirectoryStore(path=store_name)  # TODO: write directly to s3?
    root = zarr.group(store=store, path="/", overwrite=True)
    args = {'compressor': compressor, 'fill_value': np.nan}
    # Coordinate: Time
    root.create_dataset(name="/time", shape=width, chunks=TILE_SIZE, dtype='float32', **args)
    root.time.attrs['_ARRAY_DIMENSIONS'] = ['time']
    # Coordinate: Depth
    root.create_dataset(name="/depth", shape=height, chunks=TILE_SIZE, dtype='float32', **args)
    root.depth.attrs['_ARRAY_DIMENSIONS'] = ['depth']
    root.depth[:] = np.round(
        np.linspace(start=0, stop=min_echo_range * height, num=height),
        decimals=2
    )  # Note: "depth" starts at zero
    # Coordinates: Channel
    root.create_dataset(name="/channel", shape=len(channel), chunks=1, dtype='str', **args)
    root.channel.attrs['_ARRAY_DIMENSIONS'] = ['channel']
    root.channel[:] = channel
    # Latitude
    root.create_dataset(name="/latitude", shape=width, chunks=TILE_SIZE, dtype='float32', **args)
    root.latitude.attrs['_ARRAY_DIMENSIONS'] = ['time']
    # Longitude
    root.create_dataset(name="/longitude", shape=width, chunks=TILE_SIZE, dtype='float32', **args)
    root.longitude.attrs['_ARRAY_DIMENSIONS'] = ['time']
    # Frequency
    root.create_dataset(name="/frequency", shape=len(frequency), chunks=1, dtype='float32', **args)
    root.frequency.attrs['_ARRAY_DIMENSIONS'] = ['channel']
    root.frequency[:] = frequency
    # Data
    root.create_dataset(
        name="/data",
        shape=(height, width, len(channel)),
        chunks=(TILE_SIZE, TILE_SIZE, 1),
        **args
    )
    root.data.attrs['_ARRAY_DIMENSIONS'] = ['depth', 'time', 'channel']
    # TODO: add metadata from echopype conversion
    zarr.consolidate_metadata(store)
    # foo = xr.open_zarr(f'{cruise_name}.zarr')

def get_table_as_dataframe(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
) -> pd.DataFrame:
    dynamodb = session.resource(service_name='dynamodb')
    try:
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


def main(
        environment: str='DEV',
        prefix: str='rudy',
        ship_name: str='Henry_B._Bigelow',
        cruise_name: str='HB0707',
        sensor_name: str='EK60'
) -> None:
    #################################################################
    if ENV[environment] is ENV.PROD:
        OUTPUT_BUCKET = 'noaa-wcsd-zarr-pds'
    else:
        OUTPUT_BUCKET = "noaa-wcsd-pds-index"
    #
    df = get_table_as_dataframe(prefix=prefix, ship_name=ship_name, cruise_name=cruise_name, sensor_name=sensor_name)
    #################################################################
    # [2] manifest of files determines width of new zarr store
    cruise_channels = list(set([item for sublist in df['CHANNELS'].tolist() for item in sublist]))
    cruise_channels.sort()
    # Note: This values excludes nan coordinates
    consolidated_zarr_width = np.sum(df['NUM_PING_TIME_DROPNA'].astype(int))
    # [3] calculate the max/min measurement resolutions for the whole cruise
    cruise_min_echo_range = float(np.min(df['MIN_ECHO_RANGE'].astype(float)))
    # [4] calculate the largest depth value
    cruise_max_echo_range = float(np.max(df['MAX_ECHO_RANGE'].astype(float)))
    # [5] get number of channels
    cruise_frequencies = [float(i) for i in df['FREQUENCIES'][0]]
    # new_height = int(np.ceil(cruise_max_echo_range / cruise_min_echo_range / tile_size) * tile_size)
    new_height = int(np.ceil(cruise_max_echo_range) / cruise_min_echo_range)
    # new_width = int(np.ceil(total_width / tile_size) * tile_size)
    new_width = int(consolidated_zarr_width)
    #################################################################
    if ENV[environment] is ENV.PROD:
        store_name = f"{cruise_name}.zarr"
    else:
        store_name = f"{prefix}_{cruise_name}.zarr"
    #################################################################
    if os.path.exists(store_name):
        print(f'Removing local zarr directory: {store_name}')
        shutil.rmtree(store_name)
    #################################################################
    create_zarr_store(
        store_name=store_name,
        width=new_width,
        height=new_height,
        min_echo_range=cruise_min_echo_range,
        channel=cruise_channels,
        frequency=cruise_frequencies
    )
    #################################################################
    if ENV[environment] is ENV.PROD:
        # If PROD write to noaa-wcsd-zarr-pds bucket
        secret = get_secret(secret_name=SECRET_NAME)
        s3_zarr_client = boto3.client(
            service_name='s3',
            aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
            aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
        )
    else:
        # If DEV write to dev bucket
        s3_zarr_client = boto3.client(service_name='s3')
    #################################################################
    zarr_prefix = os.path.join("data", "processed", ship_name, cruise_name, sensor_name)
    upload_files(
        local_directory=store_name,
        bucket=OUTPUT_BUCKET,
        object_prefix=zarr_prefix,
        s3_client=s3_zarr_client
    )
    # Verify count of the files uploaded
    count = 0
    for subdir, dirs, files in os.walk(store_name):
        count += len(files)
    raw_zarr_files = get_raw_files(
        bucket_name=OUTPUT_BUCKET,
        sub_prefix=os.path.join(zarr_prefix, store_name)
    )
    if len(raw_zarr_files) != count:
        print(f'Problem writing {store_name} with proper count {count}.')
        raise
    if os.path.exists(store_name):
        print(f'Removing local zarr directory: {store_name}')
        shutil.rmtree(store_name)
    #
    print('done')
    #################################################################


def lambda_handler(event: dict, context: dict) -> dict:
    main(
        environment=os.environ['ENV'],  # DEV or TEST
        prefix=os.environ['PREFIX'],    # unique to each cloudformation deployment
        ship_name=os.environ['SHIP'],
        cruise_name=os.environ['CRUISE'],
        sensor_name=os.environ['SENSOR']
    )


# Zarr consolidated write reference:
# https://github.com/oftfrfbf/watercolumn/blob/8b7ed605d22f446e1d1f3087971c31b83f1b5f4c/scripts/scan_watercolumn_bucket_by_size.py

# #### TO TEST ZARR STORE IN S3 ####
# import s3fs
# s3 = s3fs.S3FileSystem(anon=True)
# store = s3fs.S3Map(root=f's3://{OUTPUT_BUCKET}/data/processed/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr', s3=s3, check=False)
# dstest = xr.open_zarr(store=store, consolidated=True)
## Persistence mode: 'r' means read only (must exist); 'r+' means read/write (must exist); 'a' means read/write (create if doesn't exist); 'w' means create (overwrite if exists); 'w-' means create
# z = zarr.open(store, mode="r+") # 'r+' means read/write (must exist)
# z.sv[...]
# type(z.sv)
# ##################################

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
