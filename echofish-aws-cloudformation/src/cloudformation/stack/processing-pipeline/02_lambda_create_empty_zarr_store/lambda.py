#!/usr/bin/env python

import os
import json
import boto3
import botocore
import numpy as np
from datetime import datetime
from botocore.config import Config
from botocore.exceptions import ClientError

import numpy as np
import xarray as xr
from numcodecs import Blosc
import zarr

import pandas as pd

# aws --profile=echofish --region=us-east-1 secretsmanager get-resource-policy --secret-id="NOAA_WCSD_ZARR_PDS_BUCKET"
# client = boto3.client('ssm')

session = boto3.Session()
max_pool_connections = 64
SECRET_NAME = "NOAA_WCSD_ZARR_PDS_BUCKET"

TEMP_OUTPUT_BUCKET = "noaa-wcsd-pds-index"

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


# ds_Sv.echo_range.values.shape
# np.where(np.max(foo) == np.nanmax(ds_Sv.echo_range.values, axis=(0, 2)))

def main(cruise: str, sensor: str, ship: str):
    # This function will run once per cruise. It should read in all the individual zarr store
    # information and create a single larger store (empty) that will later be written to.
    # [0] Read dyanmodb
    dynamodb = session.resource(service_name='dynamodb')
    ship_name = 'Henry_B._Bigelow'
    cruise_name = 'HB0707'
    sensor_name = 'EK60'
    table_name = f"{ship_name}_{cruise_name}_{sensor_name}"
    table = dynamodb.Table(table_name)
    response = table.scan()  # Scan has 1 MB limit on results --> paginate
    data = response['Items']
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        data.extend(response['Items'])

    df = pd.DataFrame(data)

    # [0.5] if overwrite is true, delete any existing Zarr store --> DANGEROUS!

    # [1] determine which files were successes and which failed
    df_success = df[df['PIPELINE_STATUS'] == 'SUCCESS']  # TODO: Change this keyword to 'SUCCESS'
    if df_success.shape[0] == 0:  # iff no successes then nothing to do
        raise

    # ['PIPELINE_TIME', 'ZARR_BUCKET', 'START_TIME', 'MAX_ECHO_RANGE',
    # 'PIPELINE_STATUS', 'NUM_ECHO_RANGE', 'ZARR_PATH', 'MIN_ECHO_RANGE',
    # 'END_TIME', 'FILENAME', 'NUM_CHANNEL', 'NUM_PING_TIME', 'CHANNELS'] # TODO: remove NUM_CHANNEL

    # [2] manifest of files determines width of new zarr store
    consolidated_zarr_channels = list(set([item for sublist in df_success['CHANNELS'].tolist() for item in sublist]))
    consolidated_zarr_channels.sort()
    # Note: This values removes missing lat/lon coordinates
    consolidated_zarr_width = np.sum(df_success['NUM_PING_TIME_DROPNA'].astype(int))

    # [3] calculate the max/min measurement resolutions for the whole cruise
    cruise_min_echo_range = np.min(df_success['MIN_ECHO_RANGE'].astype(float))  # minimum resolution

    # [4] calculate the largest depth value
    cruise_max_echo_range = np.max(df_success['MAX_ECHO_RANGE'].astype(float))

    # [5] get number of channels
    cruise_channels = consolidated_zarr_channels
    cruise_frequencies = [float(i) for i in df_success['FREQUENCIES'][0]]

    # [6] create new zarr store the full size needed in data/processed/ directory
    # new_height = int(np.ceil(cruise_max_echo_range / cruise_min_echo_range / tile_size) * tile_size)  # 8192
    new_height = int(np.ceil(cruise_max_echo_range) / cruise_min_echo_range)
    new_width = consolidated_zarr_width  # int(np.ceil(total_width / tile_size) * tile_size)  # 5120
    # new_width = int(np.ceil(total_width / tile_size) * tile_size)  # 5120
    new_channels = len(cruise_channels)
    # ...starting at line 282

    #########################################
    compressor = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
    store = zarr.DirectoryStore(path=f'{cruise_name}.zarr')  # TODO: move to s3 (authenticated)...
    root = zarr.group(store=store, path="/", overwrite=True)
    args = {'compressor': compressor, 'fill_value': np.nan}

    root.create_dataset(name="/time", shape=new_width, chunks=TILE_SIZE, dtype='float32', **args)
    root.time.attrs['_ARRAY_DIMENSIONS'] = ['time']

    root.create_dataset(name="/latitude", shape=new_width, chunks=TILE_SIZE, dtype='float32', **args)
    root.latitude.attrs['_ARRAY_DIMENSIONS'] = ['time']

    root.create_dataset(name="/longitude", shape=new_width, chunks=TILE_SIZE, dtype='float32', **args)
    root.longitude.attrs['_ARRAY_DIMENSIONS'] = ['time']

    root.create_dataset(name="/depth", shape=new_height, chunks=TILE_SIZE, dtype='float32', **args)
    root.depth.attrs['_ARRAY_DIMENSIONS'] = ['depth']
    root.depth[:] = np.round(np.linspace(start=0, stop=cruise_min_echo_range * new_height, num=new_height),
                             2)  # starts at zero

    # echodata.platform.channel
    root.create_dataset(name="/channel", shape=new_channels, chunks=1, dtype='str', **args)
    root.channel.attrs['_ARRAY_DIMENSIONS'] = ['channel']
    root.channel[:] = cruise_channels

    # echodata.platform.frequency_nominal.values = [18000., 38000., 120000., 200000.]
    new_frequencies = np.asarray([18000., 38000., 120000., 200000.])
    root.create_dataset(name="/frequency", shape=len(new_frequencies), chunks=1, dtype='float32', **args)
    root.frequency.attrs['_ARRAY_DIMENSIONS'] = ['channel']
    root.frequency[:] = new_frequencies
    #
    root.create_dataset(name="/data", shape=(new_height, new_width, new_channels), chunks=(TILE_SIZE, TILE_SIZE, 1),
                        **args)
    root.data.attrs['_ARRAY_DIMENSIONS'] = ['depth', 'time', 'channel']
    root.attrs["ship"] = ship_name
    root.attrs["cruise"] = cruise_name;  # sorted(root.attrs); root.data[:]
    # TODO: add transducer type >> look for Gavin's explanatino on github issues
    zarr.consolidate_metadata(store)  # TODO: add metadata from echopype conversion
    ####################################

    ### TEST ###
    # foo = xr.open_zarr(f'{cruise_name}.zarr')

    # [7] write to s3 bucket
    secret = get_secret(secret_name=SECRET_NAME)
    s3_zarr_client = boto3.client(
        service_name='s3',
        # aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
        # aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
    )
    zarr_directory = f"{cruise_name}.zarr"
    # zarr_prefix = os.path.join("data", "raw", ship, cruise, sensor)
    # zarr_path = data/raw/Henry_B._Bigelow/HB0707/EK60/D20070712-T231759.zarr

    zarr_prefix = os.path.join("data", "processed", ship_name, cruise_name, sensor_name)
    upload_files(
        local_directory=zarr_directory,
        bucket=TEMP_OUTPUT_BUCKET,  # WCSD_ZARR_BUCKET_NAME # TODO: CHANGE BACK!!!!
        object_prefix=zarr_prefix,  # TODO: write back to same folder as read, EK60
        s3_client=s3_zarr_client
    )
    # [8] Empty Zarr store has now been uploaded to s3
    # TODO: verify count of files uploaded


#### TO TEST ZARR STORE IN S3 ####
import s3fs

s3 = s3fs.S3FileSystem(anon=True)
store = s3fs.S3Map(
    root='s3://noaa-wcsd-pds-index/data/processed/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr',
    s3=s3,
    check=False
)
dstest = xr.open_zarr(store=store, consolidated=True)
##################################

if __name__ == '__main__':
    main()


def lambda_handler(event, context):
    # json_region = os.environ['AWS_REGION']
    # print("Processing bucket: {event['bucket']}, key: {event['key']}.")
    # message = "Processing bucket: {event['bucket']}, key: {event['key']}."
    # return {'message': message}
    main()

# Zarr consolidated write reference:
# https://github.com/oftfrfbf/watercolumn/blob/8b7ed605d22f446e1d1f3087971c31b83f1b5f4c/scripts/scan_watercolumn_bucket_by_size.py



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
