#!/usr/bin/env python

import os
import glob
import shutil
import boto3
# import logging
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from botocore.config import Config
import numpy as np
from numcodecs import Blosc
import zarr
import pandas as pd
from enum import Enum
from dateutil import parser

# TODO: Add logging
# logging.basicConfig(level=logging.DEBUG)
# logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


OVERWRITE = True
MAX_POOL_CONNECTIONS = 64
MAX_CONCURRENCY = 100
TEMPDIR = "/tmp"
TILE_SIZE = 1024


#####################################################################
class PIPELINE_STATUS(Enum):
    '''Keywords used to denote processing status in DynamoDB'''
    PROCESSING = 'PROCESSING'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'



#####################################################################
def delete_all_local_raw_and_zarr_files() -> None:
    """Used to clean up any residual files from warm lambdas
    to keep the storage footprint below the 512 MB allocation.

    Returns
    -------
    None : None
        No return value.
    """
    for i in ['*.raw*', '*.zarr']:
        for j in glob.glob(i):
            # print(f'Deleting {j}')
            if os.path.isdir(j):
                shutil.rmtree(j, ignore_errors=True)
            elif os.path.isfile(j):
                os.remove(j)


#####################################################################
def upload_zarr_store_to_s3(
        local_directory: str,
        bucket_name: str,
        object_prefix: str,
        access_key_id: str = None,
        secret_access_key: str = None,
) -> None:
    """Uploads a local Zarr store to s3 bucket with the given prefix.

    Parameters
    ----------
    local_directory : str
        Path to the root of local Zarr store
    bucket_name : str
        Name of bucket to read from.
    object_prefix : str
        Prefix path to give for written objects.
    access_key_id : str
        AWS access key id. Optional.
    secret_access_key : str
        AWS access key secret. Optional.

    Returns
    -------
    None : None
        None
    """
    client_config = Config(max_pool_connections=MAX_POOL_CONNECTIONS)
    session = boto3.Session()
    s3 = session.client(
        service_name='s3',
        config=client_config,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )
    for subdir, dirs, files in os.walk(local_directory):
        for file in files:
            local_path = os.path.join(subdir, file)
            print(local_path)
            s3_key = os.path.join(object_prefix, local_path)
            try:
                s3.upload_file(
                    Filename=local_path,
                    Bucket=bucket_name,
                    Key=s3_key,
                    Config=TransferConfig(max_concurrency=MAX_CONCURRENCY)
                )
            except ClientError as e:
                # logging.error(e)
                print(e)
    # # TODO: move elsewhere???
    # # Verify count of the files uploaded
    # count = 0
    # for subdir, dirs, files in os.walk(store_name):
    #     count += len(files)
    # raw_zarr_files = get_raw_files(
    #     bucket_name=OUTPUT_BUCKET,
    #     sub_prefix=os.path.join(zarr_prefix, store_name)
    # )
    # if len(raw_zarr_files) != count:
    #     print(f'Problem writing {store_name} with proper count {count}.')
    #     raise


#####################################################################
def find_children_objects(
        bucket_name: str,
        sub_prefix: str = None,
        access_key_id: str = None,
        secret_access_key: str = None,
) -> list:
    """Finds all child objects for a given prefix in a s3 bucket.

    Parameters
    ----------
    bucket_name : str
        Name of bucket to read from.
    sub_prefix : str
        Prefix path to folder containing children objects. Optional.
    access_key_id : str
        AWS access key id. Optional.
    secret_access_key : str
        AWS access key secret. Optional.

    Returns
    -------
    objects : list
        List of object names as strings.
    """
    client_config = Config(max_pool_connections=MAX_POOL_CONNECTIONS)
    session = boto3.Session()
    s3 = session.client(
        service_name='s3',
        config=client_config,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )
    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=sub_prefix)
    objects = []
    for page in page_iterator:
        objects.extend(page['Contents'])
    return objects


#####################################################################
def get_s3_files(
        bucket_name: str,
        sub_prefix: str,
        file_suffix: str = None,
        access_key_id: str = None,
        secret_access_key: str = None,
) -> list:
    """Get all files in a s3 bucket defined by prefix and suffix.

    Parameters
    ----------
    bucket_name : str
        Name of bucket to read from.
    sub_prefix : str
        Prefix path to folder containing children objects. Optional.
    file_suffix : str
        Suffix for which all files will be filtered by. Optional.
    access_key_id : str
        AWS access key id. Optional.
    secret_access_key : str
        AWS access key secret. Optional.

    Returns
    -------
    objects : list
        List of object names as strings.
    """
    print('Getting raw files')
    raw_files = []
    try:
        children = find_children_objects(
            bucket_name=bucket_name,
            sub_prefix=sub_prefix,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key
        )
        if file_suffix is None:
            raw_files = children
        else:
            for i in children:
                # Note any files with predicate 'NOISE' are to be ignored, see: "Bell_M._Shimada/SH1507"
                if i['Key'].endswith(file_suffix) and not os.path.basename(i['Key']).startswith(('NOISE')):
                    raw_files.append(i['Key'])
            return raw_files
    except ClientError as err:
        print(f"Some problem was encountered: {err}")
        raise
    return raw_files


def create_zarr_store(
        store_name: str,
        width: int,
        height: int,
        min_echo_range: float,
        # channel: list,
        frequency: list,
        # start_time: str,
) -> None:
    """Creates a new and empty Zarr store in a s3 bucket.

    Parameters
    ----------
    store_name : str
        Name of new Zarr store.
    width : int
        The total width of the Zarr store data. This measurement encompasses
        the sum of all NON-NA ping_times across all files for a cruise.
    height : int
        The total height of the Zarr store data. This value takes into account the
        min and max heights of all water column data to ensure that the new data
        can be gridded properly.
    min_echo_range : float
        The minimum echo range for the entire cruise.
    channel : list
        A list of all the channels associated with the cruise.
    frequency : list
        A list of the frequencies associated with each channel.
    start_time : str
        An ISO 8601 string representation for the base time that will be used to
        store timestamps (e.g. "2007-07-11T18:20:32.656Z"). This will be converted
        into a cftime.num2date with units as milliseconds since the START_TIME,
        and use a proleptic_gregorian calendar.

    Returns
    -------
    None : None
        None.
    """
    # store_name='test.zarr'
    # width=10; height=10; channel=['a', 'b', 'c']
    ###
    compressor = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
    # Note: normalize_keys sets keys to lower case characters
    store = zarr.DirectoryStore(path=store_name, normalize_keys=False)  # TODO: write directly to s3?
    root = zarr.group(store=store, overwrite=True, cache_attrs=True) # path="/",
    #####################################################################
    # Coordinate: Time -- no missing values will be included
    # https://zarr.readthedocs.io/en/stable/spec/v2.html#data-type-encoding
    # time = root.create_group(name="time")
    root.create_dataset(
        name="time",
        data=np.repeat(0., width),
        shape=width,
        chunks=TILE_SIZE,
        dtype=np.dtype('float64'),
        compressor=compressor,
        fill_value=0.,
        overwrite=True
    )
    root.time.attrs['_ARRAY_DIMENSIONS'] = ['time']
    root.time.attrs['calendar'] = 'proleptic_gregorian'
    root.time.attrs['units'] = "seconds since 1970-01-01 00:00:00"
    root.time.attrs['long_name'] = "Timestamp of each ping"
    root.time.attrs['standard_name'] = "time"
    # zzz = zarr.open('https://echofish-dev-master-118234403147-echofish-zarr-store.s3.us-west-2.amazonaws.com/GU1002_resample.zarr')
    # zzz.time[0] = 1274979445.423
    # Initialize all to origin time, will be overwritten late
    #####################################################################
    # Coordinate: Depth -- float16 == 2 significant digits
    initial_depth_data = np.round(
        np.linspace(
            start=0,
            stop=min_echo_range * height,
            num=height
        ),
        decimals=2
    ) + 0.01
    root.create_dataset(
        name="depth",
        data=initial_depth_data,
        shape=height,
        chunks=TILE_SIZE,
        dtype=np.dtype('float64'),
        compressor=compressor,
        fill_value=0.,
        overwrite=True
    )
    # TODO: PROBLEM, depth at zero is nan???
    root.depth.attrs['_ARRAY_DIMENSIONS'] = ['depth']
    root.depth.attrs['long_name'] = 'Depth below surface'
    root.depth.attrs['units'] = 'm'
    # Note: "depth" starts at zero [inclusive]
    #####################################################################
    # Latitude -- float32 == 5 significant digits
    root.create_dataset(
        name="latitude",
        data=np.repeat(0., width),
        shape=width,
        chunks=TILE_SIZE,
        dtype=np.dtype('float32'),
        compressor=compressor,
        fill_value=0.,
        overwrite=True
    )
    root.latitude.attrs['_ARRAY_DIMENSIONS'] = ['time']
    root.latitude.attrs['long_name'] = 'Latitude'
    root.latitude.attrs['units'] = 'degrees_north'
    # root.latitude[:] = np.nan
    #####################################################################
    # Longitude
    root.create_dataset(
        name="longitude",
        data=np.repeat(0., width),
        shape=width,
        chunks=TILE_SIZE,
        dtype=np.dtype('float32'),
        compressor=compressor,
        fill_value=0.,
        overwrite=True
    )
    root.longitude.attrs['_ARRAY_DIMENSIONS'] = ['time']
    root.longitude.attrs['long_name'] = 'Longitude'
    root.longitude.attrs['units'] = 'degrees_east'
    # root.longitude[:] = np.nan
    #####################################################################
    # Coordinates: Channel
    # TODO: change str to something else...
    # root.create_dataset(name="/channel", shape=len(channel), chunks=1, dtype='str', compressor=compressor)
    # root.channel.attrs['_ARRAY_DIMENSIONS'] = ['channel']
    # root.channel[:] = channel
    #####################################################################
    # Frequency
    root.create_dataset(
        name="frequency",
        data=frequency,
        shape=len(frequency),
        chunks=1,
        dtype=np.dtype('float32'),
        compressor=compressor,
        fill_value=0.,
        overwrite=True
    )
    # root.frequency.attrs['_ARRAY_DIMENSIONS'] = ['channel']
    root.frequency.attrs['_ARRAY_DIMENSIONS'] = ['frequency']  # TODO: change back to channel with string values?
    root.frequency.attrs['long_name'] = 'Transducer frequency'
    root.frequency.attrs['standard_name'] = 'sound_frequency'
    root.frequency.attrs['units'] = 'Hz'
    #####################################################################
    # Data # TODO: Note change from 'data' to 'Sv'
    root.create_dataset(
        name="Sv",
        shape=(height, width, len(frequency)),
        chunks=(TILE_SIZE, TILE_SIZE, 1),
        dtype=np.dtype('float32'),  # TODO: try to experiment with 'float16'
        compressor=compressor,
        fill_value=np.nan,
        overwrite=True
    )
    root.Sv.attrs['_ARRAY_DIMENSIONS'] = ['depth', 'time', 'frequency']
    root.Sv.attrs['long_name'] = 'Volume backscattering strength (Sv re 1 m-1)'
    root.Sv.attrs['units'] = 'dB'
    zarr.consolidate_metadata(store=store_name)
    #####################################################################
    #import xarray as xr
    #foo = xr.open_zarr(f'{cruise_name}.zarr')
    assert(
        os.path.exists(store_name)
    ), "Problem: Zarr store was not found."


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

    Notes
    -----
    Only files marked SUCCESS will be aggregated into the larger store, others
    will be ignored.
    """
    session = boto3.Session()
    dynamodb = session.resource(service_name='dynamodb')
    try:
        table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
        table_name = 'rudy-dev-echofish-EchoFish-File-Info'
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
    # assert(
    #     not np.any(df['PIPELINE_STATUS'] == PIPELINE_STATUS.PROCESSING.value)
    # ), f"None of the PIPELINE_STATUS fields should still be {PIPELINE_STATUS.PROCESSING.value}."
    df = df[df['PIPELINE_STATUS'] != 'FAILURE']
    df = df[df['PIPELINE_STATUS'] != 'PROCESSING']
    if df.shape[0] == 0:
        raise
    return df.sort_values(by='START_TIME', ignore_index=True)


def get_file_count(
        store_name: str
) -> int:
    """Get a count of files in the local Zarr store. Hopefully this
    can be improved upon as this is currently a _very_ crude checksum
    to ensure that all files are being read & written properly.

    Parameters
    ----------
    store_name : str
        A Zarr store in the local directory.

    Returns
    -------
    Count of files : int
        Count of files in the Zarr store.
    """
    count = 0  # count number of local zarr files
    for subdir, dirs, files in os.walk(store_name):
        count += len(files)
    return count


def main(
        prefix: str='rudy',
        ship_name: str='Henry_B._Bigelow',
        cruise_name: str='HB0707',
        sensor_name: str='EK60',
        output_bucket: str='noaa-wcsd-zarr-pds',
) -> None:
    """This Lambda runs once per cruise. It gets data from DynamoDB to
    get stats on how to build an empty Zarr store at the cruise level.
    After computing min and max widths/heights we are able to create
    the empty store and write to an S3 bucket.

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
    output_bucket : str
        Bucket where files are written to. Can be the NOAA NODD bucket if the
        proper credentials are provided.

    Returns
    -------
    None : None
        None
    """
    #################################################################
    # aws --profile wcsdzarr s3 rm s3://noaa-wcsd-zarr-pds/level_2/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr/ --recursive
    # AWS Lambda requires writes only in /tmp directory
    os.chdir(TEMPDIR)
    print(os.getcwd())
    #################################################################
    df = get_table_as_dataframe(
        prefix=prefix,
        ship_name=ship_name,
        cruise_name=cruise_name,
        sensor_name=sensor_name
    )
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
    store_name = f"{cruise_name}.zarr"
    #################################################################
    delete_all_local_raw_and_zarr_files()
    #################################################################
    create_zarr_store(
        store_name=store_name,
        width=new_width,
        height=new_height,
        min_echo_range=cruise_min_echo_range,
        # channel=cruise_channels,
        frequency=cruise_frequencies,
        # start_time=df.iloc[0]['START_TIME']
    )
    xx = xr.open_zarr(store_name, consolidated=False)
    xx
    zz = zarr.open(store_name)
    zz.depth.info
    #################################################################
    zarr_prefix = os.path.join("level_2", ship_name, cruise_name, sensor_name)
    #
    upload_zarr_store_to_s3(
        local_directory=store_name,
        bucket_name=output_bucket,
        object_prefix=zarr_prefix,
        access_key_id=os.getenv('ACCESS_KEY_ID'),
        secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
    )
    # https://noaa-wcsd-zarr-pds.s3.amazonaws.com/index.html
    ###########
    # Verify count of the files uploaded
    count = get_file_count(store_name=store_name)
    #
    raw_zarr_files = get_s3_files( # TODO: just need count
        bucket_name=output_bucket,
        sub_prefix=os.path.join(zarr_prefix, store_name),
        access_key_id=os.getenv('ACCESS_KEY_ID'),
        secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
    )
    if len(raw_zarr_files) != count:
        print(f'Problem writing {store_name} with proper count {count}.')
        raise
    ###########
    if os.path.exists(store_name):
        print(f'Removing local zarr directory: {store_name}')
        shutil.rmtree(store_name)
    #
    print('done')
    #################################################################


def lambda_handler(event: dict, context: dict) -> dict:
    main(
        prefix=os.environ['PREFIX'],  # unique to each cloudformation deployment
        ship_name=os.environ['SHIP'],
        cruise_name=os.environ['CRUISE'],
        sensor_name=os.environ['SENSOR'],
        output_bucket=os.environ["noaa-wcsd-zarr-pds"],
    )
    return {}






# Zarr consolidated write reference:
# https://github.com/oftfrfbf/watercolumn/blob/8b7ed605d22f446e1d1f3087971c31b83f1b5f4c/scripts/scan_watercolumn_bucket_by_size.py

# #### TO TEST ZARR STORE IN S3 ####
# import s3fs
# s3 = s3fs.S3FileSystem(anon=True)
## store = s3fs.S3Map(root=f's3://{OUTPUT_BUCKET}/data/processed/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr', s3=s3, check=False)
# store = s3fs.S3Map(root=f's3://noaa-wcsd-zarr-pds/level_2/Henry_B._Bigelow/HB0707/EK60/HB0707.zarr', s3=s3, check=False)
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
