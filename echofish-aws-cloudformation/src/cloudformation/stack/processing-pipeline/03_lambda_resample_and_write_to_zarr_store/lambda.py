#!/usr/bin/env python

# https://github.com/oftfrfbf/watercolumn/blob/master/scripts/zarr_upsample.py

import os
import boto3
# import logging
from typing import Union
import s3fs
import zarr
from scipy import interpolate
import geopandas
from botocore.exceptions import ClientError
import numpy as np
import xarray as xr
import pandas as pd
from enum import Enum

# zarr.__version__ '2.14.2'
# pd.__version__ '1.5.3'
# np.__version__ '1.24.3'
# xr.__version__ '2023.5.0'

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
    """
    Keywords used to denote processing status in DynamoDB
    """
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
        np.all(df['PIPELINE_STATUS'] == PIPELINE_STATUS.SUCCESS.value)
    ), "None of the status fields should still be processing."
    df_success = df[df['PIPELINE_STATUS'] == PIPELINE_STATUS.SUCCESS.value]
    if df_success.shape[0] == 0:
        raise
    return df_success.sort_values(by='START_TIME', ignore_index=True)


#####################################################################
def get_spatiotemporal_indices(
        input_zarr_bucket: str,
        input_zarr_path: str,
) -> tuple:
    """
    Assumes that there is a GeoJSON file in the file-level Zarr store.

    :param str input_zarr_bucket: Input bucket where file-level Zarr store exists.
    :param str input_zarr_path: Input bucket path where file-level Zarr store exists.
    :return: (list, list, list): Returns the latitude, longitude, and epoch seconds
    needed to properly index the data.
    """
    s3 = s3fs.S3FileSystem(
        key=os.getenv('ACCESS_KEY_ID'),  # optional parameter
        secret=os.getenv('SECRET_ACCESS_KEY'),
    )
    geo_json_s3_path = f's3://{input_zarr_bucket}/{input_zarr_path}/geo.json'
    assert(s3.exists(geo_json_s3_path)), "S3 GeoJSON file does not exist."
    geo_json = geopandas.read_file(
        filename=geo_json_s3_path,
        storage_options={
            "key": os.getenv('ACCESS_KEY_ID'),  # Optional values
            "secret": os.getenv('SECRET_ACCESS_KEY'),
        },
    )
    geo_json.id = pd.to_datetime(geo_json.id)
    geo_json.id.astype('datetime64[ns]')  # TODO: be careful with conversions for pandas >=2.0.0
    epoch_seconds = (
        pd.to_datetime(geo_json.dropna().id, unit='s', origin='unix') - pd.Timestamp('1970-01-01')
    ) / pd.Timedelta('1s')
    epoch_seconds = epoch_seconds.tolist()
    longitude = geo_json.dropna().longitude.tolist()
    latitude = geo_json.dropna().latitude.tolist()
    #
    return latitude, longitude, epoch_seconds


# TODO: need to pass in key/secret as optionals
def s3_zarr_as_xr(s3_zarr_store_path: str) -> xr.core.dataset.Dataset:
    """Reads an existing Zarr store in a s3 bucket.

    Parameters
    ----------
    s3_zarr_store_path : str
        S3 path to the Zarr store.

    Returns
    -------
    file_zarr : xarray.core.dataset.Dataset
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
    store = s3fs.S3Map(root=s3_zarr_store_path, s3=s3_fs, check=True)
    # You are already using dask, this is assumed by open_zarr, not the same as open_dataset(engine=“zarr”)
    import fsspec

    return xr.open_zarr(store=store, consolidated=None) # synchronizer=SYNCHRONIZER

def read_s3_geo_json(
        s3_geo_json_path: str,
        access_key_id: str = None,
        secret_access_key: str = None,
) -> str:
    # reads geojson file from s3 bucket w boto3
    session = boto3.Session()
    s3 = boto3.resource(
        service_name='s3',
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )
    # s3_geo_json_path=f's3://{input_zarr_bucket}/{input_zarr_path}/geo.json'
    content_object = s3.Object(input_zarr_bucket, f'{input_zarr_path}/geo.json')
    file_content = content_object.get()['Body'].read().decode('utf-8')
    json_content = json.loads(file_content)
    return json_content



def s3_zarr(
        output_zarr_bucket: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
        # zarr_synchronizer: Union[str, None] = None,
):
    # Environment variables are optional parameters
    s3 = s3fs.S3FileSystem(
        key=os.getenv('ACCESS_KEY_ID'),
        secret=os.getenv('SECRET_ACCESS_KEY'),
    )
    root = f's3://{output_zarr_bucket}/level_2/{ship_name}/{cruise_name}/{sensor_name}/{cruise_name}.zarr'
    # TODO: check if directory exists
    store = s3fs.S3Map(root=root, s3=s3, check=True)
    # TODO: properly synchronize with efs mount
    # TODO: zarr.ThreadSynchronizer()
    # Note: 'r+' means read/write (store must already exist)
    cruise_zarr = zarr.open(store=store, mode="r+") #, zarr_synchronizer=zarr_synchronizer)
    return cruise_zarr


def interpolate_data(
        minimum_resolution: float,  # get from df
        maximum_cruise_depth_meters: float,  # get from df
        file_xr: xr.Dataset,  # need to figure out which time values are removed
        cruise_zarr: zarr.Group,
        start_ping_time_index: int,
        end_ping_time_index: int,
        indices: np.ndarray, # the file_xr ping_time and Sv indices that are not np.nan
) -> np.ndarray:
    # Note: file_zarr dimensions are (frequency, time, depth)
    # read remotely once to speed up
    frequencies = file_xr.channel.shape[0]
    file_sv = file_xr.Sv.values  # (4, 9779, 1302)
    all_file_depth_values = file_xr.echo_range.values[:, :, :]  # TODO
    # Note: cruise_zarr dimensions are (depth, time, frequency)
    cruise_sv_subset = np.empty(shape=cruise_zarr.sv[:, start_ping_time_index:end_ping_time_index, :].shape)
    cruise_sv_subset[:, :, :] = np.nan # (5208, 9778, 4)
    # grid evenly spaced depths over the specified interval
    all_cruise_depth_values = np.linspace(
        start=0,
        stop=maximum_cruise_depth_meters,
        num=int(maximum_cruise_depth_meters / minimum_resolution) + 1,
        endpoint=True
    )  # 5208
    #
    for iii in range(frequencies):
        for jjj in range(len(indices)):
            y = file_sv[iii, indices[jjj], :]  # y.shape = (4, 4871, 5208) -> frequency, time, depth
            # all_Sv is inly 1302 depth measurements
            f = interpolate.interp1d(  # Interpolate a 1-D function.
                x=all_file_depth_values[iii, indices[jjj], :],
                y=y,  # Need to strip off unwanted timestamps
                kind='nearest',
                # axis=0,
                bounds_error=False,
                fill_value=np.nan
            )
            y_new = f(all_cruise_depth_values)  # y_new.shape = (4, 4871, 5208) --> (frequency, time, depth)
            # Note: dimensions are (depth, time, frequency)
            cruise_sv_subset[:, jjj, iii] = y_new #.transpose((2, 1, 0))  # (5208, 89911, 4)
    #
    return cruise_sv_subset


# Based off of: https://github.com/oftfrfbf/watercolumn/blob/master/scripts/zarr_upsample.py
# file_info = {
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


#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/

#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070711-T182032.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070711-T210709.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T004447.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T033431.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T061745.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T100505.zarr'

#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T124906.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T152416.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T171804.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T201647.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T202050.zarr'
#input_zarr_path = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T231759.zarr'


def main(
    context: dict,
    prefix: str = 'rudy',
    ship_name: str = 'Henry_B._Bigelow',
    cruise_name: str = 'HB0707',
    sensor_name: str = 'EK60',
    input_zarr_path: str = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T152416.zarr',
    # input_zarr_path: str = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070711-T182032.zarr'
    # input_zarr_path: str = 'level_1/Henry_B._Bigelow/HB0707/EK60/D20070712-T152416.zarr'
    # zarr_synchronizer: Union[str, None] = None,
) -> None:
    """This Lambda runs once per file-level Zarr store. It begins by
    resampling the data for a file-level Zarr store. It then gets
    data from DynamoDB to determine time indicies for where in the larger
    cruise-level Zarr store to write the regridded subset of file-level
    Zarr data.

    Parameters
    ----------
    context : dict
        The AWS context passed down from handler.
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
        in parallel. Uses thread locks. Will need to be an efs mount shared
        between all the lambdas.

    Returns
    -------
    None : None
        No return value.
    """
    #################################################################
    os.chdir(TEMPDIR)  # run code in /tmp directory for lambda
    #################################################################
    # [0] get dynamoDB table info
    df = get_table_as_dataframe(
        prefix=prefix,
        ship_name=ship_name,
        cruise_name=cruise_name,
        sensor_name=sensor_name,
    )
    # Zarr path is derived from DynamoDB
    assert(input_zarr_path in list(df['ZARR_PATH'])), "The Zarr path is not found in the database."
    #
    index = df.index[df['ZARR_PATH'] == input_zarr_path][0]
    print(index)
    #
    file_info = df.iloc[index].to_dict()
    input_zarr_bucket = file_info['ZARR_BUCKET']
    input_zarr_path = file_info['ZARR_PATH']
    output_zarr_bucket = file_info['ZARR_BUCKET']
    #
    #################################################################
    # [1] read file-level Zarr store using xarray
    file_xr = s3_zarr_as_xr(
        s3_zarr_store_path=f's3://{input_zarr_bucket}/{input_zarr_path}'
    )
    geo_json = read_s3_geo_json(
        s3_geo_json_path=f's3://{input_zarr_bucket}/{input_zarr_path}/geo.json',
        access_key_id=os.getenv('ACCESS_KEY_ID'),
        secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
    )
    #geo_json['features'][0]
    # {'id': '2007-07-12T15:24:16.032000000', 'type': 'Feature', 'properties': {'latitude': None, 'longitude': None}, 'geometry': None}
    # reads GeoJSON with the id as the index
    geospatial = geopandas.GeoDataFrame.from_features(geo_json['features']).set_index(pd.json_normalize(geo_json["features"])["id"].values)
    geospatial_index = geospatial.dropna().index.values.astype('datetime64[ns]')
    # find the indices where 'v' can be inserted into 'a'
    indices = np.searchsorted(a=file_xr.ping_time.values, v=geospatial_index)
    #
    # TODO: only need to read the geojson file once instead of twice here...
    #
    #########################################################################
    #########################################################################
    # [2] open cruise level zarr store for writing
    # output_zarr_path: str = f'',
    cruise_zarr = s3_zarr(
        output_zarr_bucket,
        ship_name,
        cruise_name,
        sensor_name,
        # zarr_synchronizer
    )
    #########################################################################
    # [3] Get needed indices
    # https://github.com/oftfrfbf/watercolumn/blob/8b7ed605d22f446e1d1f3087971c31b83f1b5f4c/scripts/scan_watercolumn_bucket_by_size.py#L138
    # Offset from start index to insert new data. Note that missing values are excluded.
    ping_time_cumsum = np.insert(
        np.cumsum(df['NUM_PING_TIME_DROPNA'].to_numpy(dtype=int)),
        obj=0,
        values=0
    )
    start_ping_time_index = ping_time_cumsum[index]
    end_ping_time_index = ping_time_cumsum[index + 1]
    #
    #########################################################################
    # [4] extract gps and time coordinate from file-level Zarr store,
    # write subset of ping_time to the larger zarr store
    # reference: https://osoceanacoustics.github.io/echopype-examples/echopype_tour.html
    latitude, longitude, epoch_seconds = get_spatiotemporal_indices(input_zarr_bucket, input_zarr_path)
    assert(
        len(epoch_seconds) == len(cruise_zarr.time[start_ping_time_index:end_ping_time_index])
    ), "Number of the timestamps is not equivalent to indices given."
    cruise_zarr.time[start_ping_time_index:end_ping_time_index] = epoch_seconds
    #########################################################################
    # [5] write subset of latitude/longitude
    cruise_zarr.latitude[start_ping_time_index:end_ping_time_index] = latitude
    cruise_zarr.longitude[start_ping_time_index:end_ping_time_index] = longitude
    #########################################################################
    # [6] get interpolated Sv data
    filename = os.path.basename(input_zarr_path)
    all_Sv_prototype = interpolate_data(
        minimum_resolution = np.nanmin(np.float32(df['MIN_ECHO_RANGE'])),
        maximum_cruise_depth_meters = np.max(np.float32(df['MAX_ECHO_RANGE'])),
        # num_ping_time_dropna = int(df.iloc[index]['NUM_PING_TIME_DROPNA']),
        file_xr=file_xr,
        cruise_zarr=cruise_zarr,
        start_ping_time_index=start_ping_time_index,
        end_ping_time_index=end_ping_time_index,
        indices=indices,
    )  # TODO:
    cruise_zarr.sv[:, start_ping_time_index:end_ping_time_index, :] = all_Sv_prototype
    #
    #np.nanmean(cruise_zarr.sv[:, start_ping_time_index:end_ping_time_index, :])
    #

    #
    cruise_zarr.sv.info
    print('done')
# logger.info("Finishing lambda.")
    # TODO: Work on synchronizing the data as written


#####################################################################
def lambda_handler(event: dict, context: dict) -> dict:
    # print_diagnostics(context)
    main(
        context=context,
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
docker build -f Dockerfile_OBSOLETE -t my-local-lambda:v1 . --no-cache
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
