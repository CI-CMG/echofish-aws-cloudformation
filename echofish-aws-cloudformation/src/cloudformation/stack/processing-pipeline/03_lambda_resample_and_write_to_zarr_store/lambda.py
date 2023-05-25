#!/usr/bin/env python

# https://github.com/oftfrfbf/watercolumn/blob/master/scripts/zarr_upsample.py

import os
import json
import boto3
# import logging
import botocore
import aiobotocore
from typing import Union
import s3fs
import geopandas
from botocore.config import Config
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig
import numpy as np
import xarray as xr
import pandas as pd
from enum import Enum

# TODO: Add logging
# logging.basicConfig(level=logging.DEBUG)
# logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

OVERWRITE = True
MAX_POOL_CONNECTIONS = 64
MAX_CONCURRENCY = 100
TEMPDIR = "/tmp"
TILE_SIZE = 1024

# TODO: implement
SYNCHRONIZER = None # TODO: this will need to be shared between parallel lambdas
#                   # maybe will need to mount an elastic file system

#####################################################################
class PIPELINE_STATUS(Enum):
    '''Keywords used to denote processing status in DynamoDB'''
    PROCESSING = 'PROCESSING'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'

#####################################################################

def get_table_as_dataframe(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
) -> pd.DataFrame:
    """Reads DynamoDB processing table as Pandas dataframe.

    Parameters
    ----------
    prefix : str
        String prefix for the table name.
    ship_name : str
        Ship name.
    cruise_name : str
        Name of the cruise.
    sensor_name : str
        Name of the sensor, e.g. EK60.

    Returns
    -------
    Pandas Dataframe : pd.DataFrame
        A Dataframe of the file-level Zarr stores and associated information.
        The data is sorted by START_TIME.

    Notes
    -----
    Only files marked SUCCESS will be aggregated into the larger store, others
    will be ignored.
    """
    session = boto3.Session()
    dynamodb = session.resource(service_name='dynamodb')
    try:
        table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
        table = dynamodb.Table(table_name)
        # Note: table.scan() has 1 MB limit on results so pagination is used.
        response = table.scan()
        data = response['Items']
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            data.extend(response['Items'])
    except ClientError as err:
        print('Problem finding the dynamodb table')
        raise err
    df = pd.DataFrame(data)
    assert( #
        np.all(df['PIPELINE_STATUS'] != PIPELINE_STATUS.PROCESSING.value)
    ), "None of the status fields should still be processing."
    df_success = df[df['PIPELINE_STATUS'] == PIPELINE_STATUS.SUCCESS.value]
    if df_success.shape[0] == 0:
        raise
    return df_success.sort_values(by='START_TIME', ignore_index=True)

#####################################################################
#### BELOW IS CONSOLIDATED FROM PREVIOUS PROJECT ####
# def print_diagnostics(context):
#     # print(f"TEMPDIR: {TEMPDIR}")
#     print(f"Lambda function ARN: {context.invoked_function_arn}")
#     print(f"CloudWatch log stream name: {context.log_stream_name}")
#     print(f"CloudWatch log group name: {context.log_group_name}")
#     print(f"Lambda Request ID: {context.aws_request_id}")
#     print(f"Lambda function memory limits in MB: {context.memory_limit_in_mb}")
#     print(f"Lambda time remaining in MS: {context.get_remaining_time_in_millis()}")
#     print(f"_HANDLER: {os.environ['_HANDLER']}")
#     print(f"AWS_EXECUTION_ENV: {os.environ['AWS_EXECUTION_ENV']}")
#     # print(f"AWS_LAMBDA_FUNCTION_MEMORY_SIZE: {os.environ['AWS_LAMBDA_FUNCTION_MEMORY_SIZE']}")


#####################################################################

# TODO: need to pass in key/secret as optionals
def read_s3_zarr_store(
        s3_zarr_store_path: str='s3://noaa-wcsd-zarr-pds/level_2/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr'
) -> xr.core.dataset.Dataset:
    """Reads an existing Zarr store in a s3 bucket.

    Parameters
    ----------
    s3_zarr_store_path : str
        S3 path to the Zarr store.

    Returns
    -------
    Dataset : xarray.core.dataset.Dataset
        File-level Zarr store opened as Xarray Dataset.

    Notes
    -----
    # import zarr
    # # Persistence mode: 'r' means read only (must exist); 'r+' means read/write (must exist);
    # z = zarr.open(store, mode="r+") # 'r+' means read/write (must exist)
    # z.Sv[:].shape
    # # (5208, 89911, 4)
    """
    s3_fs = s3fs.S3FileSystem(
        key=os.getenv('ACCESS_KEY_ID'),  # optional parameter
        secret=os.getenv('SECRET_ACCESS_KEY'),
    )
    store = s3fs.S3Map(root=s3_zarr_store_path, s3=s3_fs, check=False)
    return xr.open_zarr(store=store, synchronizer=SYNCHRONIZER, consolidated=True)

# TODO: will need to input just the zarr store name,

def main(
    prefix: str = 'rudy',
    ship_name: str = 'Henry_B._Bigelow',
    cruise_name: str = 'HB0707',
    sensor_name: str = 'EK60',
    input_zarr_path: str = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070711-T210709.zarr',
    output_zarr_bucket: str = 'noaa-wcsd-zarr-pds',
    output_zarr_path: str = 'level_2/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr',
    zarr_synchronizer: Union[str, None] = None,
) -> None:
    # https://github.com/oftfrfbf/watercolumn/blob/master/scripts/zarr_upsample.py
    #################################################################
    """This Lambda runs once per file-level Zarr store. It begins by
    resampling the data for a file-level Zarr store. It then gets
    data from DynamoDB to determine time indicies for where in the larger
    cruise-level Zarr store to write the regridded subset of file-level
    Zarr data.

    Parameters
    ----------
    prefix : str
        The desired prefix for this specific deployment of the template.
    ship_name : str
        Name of the ship, e.g. Henry_B._Bigelow.
    cruise_name : str
        Name of the cruise, e.g. HB0707.
    sensor_name : str
        The type of echosounder, e.g. EK60.
    zarr_bucket : str
        Bucket where files are written to. Can be the NOAA NODD bucket if the
        proper credentials are provided.
    zarr_path : str
        Path to Zarr store in s3 bucket.
    zarr_synchronizer : str
        Path to Zarr synchronizer which is shared between lambdas writing
        in parallel. Uses thread locks.

    Returns
    -------
    None : None
        No return value.
    """
    #################################################################
    os.chdir(TEMPDIR)  # run code in /tmp directory
    #################################################################
    # [0] get dynamoDB table info ####################################
    df = get_table_as_dataframe(
        prefix=prefix,
        ship_name=ship_name,
        cruise_name=cruise_name,
        sensor_name=sensor_name,
    )
    # zarr_path = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070711-T182032.zarr'
    # zarr_path = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070711-T210709.zarr'
    zarr_path = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070712-T004447.zarr'
    #
    index = df.index[df['ZARR_PATH'] == zarr_path][0]; print(index)
    file_info = df.iloc[index].to_dict()
    # store_info = {
    #     'PIPELINE_TIME': '2023-05-23T13:45:10Z',
    #     'FILE_NAME': 'D20070711-T182032.raw',
    #     'START_TIME': '2007-07-11T18:20:32.656Z',
    #     'ZARR_BUCKET': 'noaa-wcsd-zarr-pds',
    #     'MAX_ECHO_RANGE': Decimal('249.792'),
    #     'NUM_PING_TIME_DROPNA': Decimal('9778'),
    #     'PIPELINE_STATUS': 'SUCCESS',
    #     'ZARR_PATH': 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070711-T182032.zarr',
    #     'CRUISE_NAME': 'HB0707',
    #     'MIN_ECHO_RANGE': Decimal('0.192'),
    #     'FREQUENCIES': [Decimal('18000'), Decimal('38000'), Decimal('120000'), Decimal('200000')],
    #     'END_TIME': '2007-07-11T21:07:08.360Z',
    #     'SENSOR_NAME': 'EK60',
    #     'SHIP_NAME': 'Henry_B._Bigelow',
    #     'CHANNELS': ['GPT  18 kHz 009072056b0e 2 ES18-11', 'GPT  38 kHz 0090720346bc 1 ES38B', 'GPT 120 kHz 0090720580f1 3 ES120-7C', 'GPT 200 kHz 009072034261 4 ES200-7C']
    # }
    input_zarr_bucket = file_info['ZARR_BUCKET']
    input_zarr_path = file_info['ZARR_PATH']
    #
    #df.iloc[:index]['NUM_PING_TIME_DROPNA']
    # TODO: Fix this to accommodate
    start_ping_time_index = np.cumsum(df.iloc[:index]['NUM_PING_TIME_DROPNA']).values[-1]
    end_ping_time_index = int(start_ping_time_index + df.iloc[index]['NUM_PING_TIME_DROPNA'])
    #################################################################
    #################################################################
    # [1] read file-level Zarr store using xarray
    file_level_zarr_store = read_s3_zarr_store(
        s3_zarr_store_path=f's3://{input_zarr_bucket}/{input_zarr_path}'
    )
    #########################################################################
    # [2] extract gps and time coordinate from file-level Zarr store
    # reference: https://osoceanacoustics.github.io/echopype-examples/echopype_tour.html
    # TODO: fix this for private bucket access
    geo_json = geopandas.read_file(f's3://noaa-wcsd-zarr-pds/data/raw/Henry_B._Bigelow/HB0707/EK60/D20070712-T004447.zarr/geo.json')
    # TODO: get concave hull with https://pypi.org/project/alphashape/
    #########################################################################
    # [4] open cruise level zarr store for writing
    # TODO: need to open with Zarr library, not xarray!
    import s3fs; import os
    s3_fs = s3fs.S3FileSystem(
        key=os.getenv('ACCESS_KEY_ID'),  # TODO: treat as optional parameter
        secret=os.getenv('SECRET_ACCESS_KEY'),
    )
    print(s3_fs.session.profile)
    store = s3fs.S3Map(root=f's3://noaa-wcsd-zarr-pds/level_2/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr', s3=s3_fs, check=False)
    import xarray as xr
    cruise_zarr = xr.open_zarr(store=store, synchronizer=None, consolidated=True)
#########################################################################
# [5] Get indexing correct so that we can
# https://github.com/oftfrfbf/watercolumn/blob/8b7ed605d22f446e1d1f3087971c31b83f1b5f4c/scripts/scan_watercolumn_bucket_by_size.py#L138
total_width_traversed = 0
index = df.index[df['ZARR_PATH'] == zarr_path][0]
ping_time_cumsum = np.insert( np.cumsum( df['NUM_PING_TIME_DROPNA'].to_numpy(dtype=int) ), obj=0, values=0 )
start_ping_time_index = np.cumsum(df.iloc[:index]['NUM_PING_TIME_DROPNA']).values[-1]

end_ping_time_index = int(start_ping_time_index + df.iloc[index]['NUM_PING_TIME_DROPNA'])

width = ds_temp.Sv.ping_time.shape[0] # ds_temp.Sv.shape[1]
height = ds_temp.Sv.range_sample.shape[0] # ds_temp.Sv.shape[0]
channels = ds_temp.Sv.channel.shape[0]

start_index = total_width_traversed  # start_index
end_index = total_width_traversed + width  # end_index
print(
    f"width: {width},"
    f"height: {height},"
    f"total_width_traversed: {total_width_traversed},"
    f"s: {start_index}, e: {end_index}"
)


#########################################################################
# [5] write subset of time to the larger zarr store
# https://github.com/oftfrfbf/watercolumn/blob/master/scripts/test_overwrite_s3.py
s3 = s3fs.S3FileSystem(
    key=os.getenv('ACCESS_KEY_ID'),  # optional parameter
    secret=os.getenv('SECRET_ACCESS_KEY'),
)
store = s3fs.S3Map(root=f's3://noaa-wcsd-zarr-pds/level_2/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr', s3=s3, check=True)
import zarr
z = zarr.open(store=store, mode="r+") # 'r+' means read/write (store must already exist)
#z.latitude[1] = 1.1
#z.latitude[3] = 3.3
### above works ###


#########################################################################
# [6] write subset of latitude to the larger zarr store

#########################################################################
# [7] write subset of longitude to the larger zarr store

#########################################################################
# [8] write subset of _ to the larger zarr store

#########################################################################
# [9] write subset of _ to the larger zarr store

z.latitude[start_index:end_index] = geo_json.latitude[~np.isnan(geo_json.latitude)].to_numpy()
z.longitude[start_index:end_index] = geo_json.longitude[~np.isnan(geo_json.longitude)].to_numpy()

# z_resample.latitude[start_index:end_index] = np.round(geo_json['latitude'].values, 5)  # round
# z_resample.longitude[start_index:end_index] = np.round(geo_json['longitude'].values, 5)
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

#####################################################################
def lambda_handler(event: dict, context: dict) -> dict:
    print_diagnostics(context)
    main(
        prefix=os.environ['PREFIX'],
        ship_name=os.environ['SHIP'],
        cruise_name=os.environ['CRUISE'],
        sensor_name=os.environ['SENSOR'],
        input_bucket=os.environ["noaa-wcsd-zarr-pds"], # TODO: these should be the same?!
        output_bucket=os.environ["noaa-wcsd-zarr-pds"],
    )
    return {}

#####################################################################

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
