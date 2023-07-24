#!/usr/bin/env python

import os
import json
import glob
import shutil
import echopype as ep
import boto3
from boto3.s3.transfer import TransferConfig
import numpy as np
import pandas as pd
import geopandas
from datetime import datetime
from botocore.config import Config
from botocore.exceptions import ClientError
from collections.abc import Generator
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FILE_SUFFIX = '.raw'
OVERWRITE = True
MAX_POOL_CONNECTIONS = 64
MAX_CONCURRENCY = 100
TEMPDIR = "/tmp"  # tempfile.gettempdir()


# TODO: Add methods for updating errors as FAILURE in DynamoDB

# TODO: will this work with SQS batch processing idempotency

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
            print(f'Deleting {j}')
            if os.path.isdir(j):
                shutil.rmtree(j, ignore_errors=True)
            elif os.path.isfile(j):
                os.remove(j)


#####################################################################
def download_raw_file(
        input_bucket: str, raw_file: str
):
    s3_session = boto3.Session()
    client_config = Config(max_pool_connections=MAX_POOL_CONNECTIONS)
    s3 = s3_session.client(service_name='s3', config=client_config)
    s3.download_file(
        Bucket=input_bucket,
        Key=raw_file,
        Filename=os.path.basename(raw_file),
        Config=TransferConfig(max_concurrency=MAX_CONCURRENCY)
    )


#####################################################################
def chunked(
        ll: list,
        n: int
) -> Generator:
    """Yields successively n-sized chunks from ll.

    Parameters
    ----------
    ll : list
        List of all objects.
    n : int
        Chunk size to break larger list down from.

    Returns
    -------
    Batches : Generator
        Breaks the data into smaller chunks for processing
    """
    for i in range(0, len(ll), n):
        yield ll[i:i + n]


#####################################################################
def delete_remote_objects(
        raw_zarr_files: list,
        output_bucket: str,
        access_key_id: str = None,
        secret_access_key: str = None,
) -> None:
    """Delete objects in s3 bucket. Deletion is limited
    to groups of 100 at a time.

    Parameters
    ----------
    raw_zarr_files : list
        Files to delete.
    output_bucket : str
        Prefix path to folder containing children objects.
    aws_access_key_id : str
        AWS access key id. Optional.
    aws_secret_access_key : str
        AWS access key secret. Optional.

    Returns
    -------
    None
    """
    s3_session = boto3.Session()
    client_config = Config(max_pool_connections=MAX_POOL_CONNECTIONS)
    s3 = s3_session.client(
        service_name='s3',
        config=client_config,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )
    objects_to_delete = []
    for raw_zarr_file in raw_zarr_files:
        objects_to_delete.append({'Key': raw_zarr_file['Key']})
    # Delete in groups of 100 -- Boto3 constraint.
    for batch in chunked(objects_to_delete, 100):
        # print(f"0: {batch[0]}, -1: {batch[-1]}")
        deleted = s3.delete_objects(
            Bucket=output_bucket,
            Delete={
                "Objects": batch
            }
        )
        print(f"Deleted {len(deleted['Deleted'])} files")


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
    page_iterator = s3.get_paginator('list_objects_v2').paginate(Bucket=bucket_name, Prefix=sub_prefix)
    objects = []
    for page in page_iterator:
        if 'Contents' in page.keys():
            objects.extend(page['Contents'])
    return objects


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
        Prefix path to give for written objects. An example of the prefix
        is "/level_1/Henry_B._Bigelow/HB0707/EK60/".
    access_key_id : str
        AWS access key id. Optional.
    secret_access_key : str
        AWS access key secret. Optional.

    Returns
    -------
    None : None
        None
    """
    print('Upload Zarr store to s3')
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
            # print(local_path)
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
    print('Getting raw s3 files')
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
                # cruise for more details.
                if i['Key'].endswith(file_suffix) and not os.path.basename(i['Key']).startswith(('NOISE')):
                    raw_files.append(i['Key'])
            return raw_files
    except ClientError as err:
        print(f"Some problem was encountered: {err}")
        raise
    return raw_files


#####################################################################
# TODO: this db should be ephemeral — MOVE TO ORCHESTRATOR
def create_table(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
) -> None:
    # TODO: TEMPORARY — MOVE TO ORCHESTRATOR
    print('Creating table')
    dynamodb = boto3.Session().client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
    existing_tables = dynamodb.list_tables()['TableNames']
    if table_name not in existing_tables:
        params = {
            'TableName': table_name,
            'KeySchema': [
                {'AttributeName': 'FILE_NAME', 'KeyType': 'HASH'},
                {'AttributeName': 'CRUISE_NAME', 'KeyType': 'RANGE'}
            ],
            'AttributeDefinitions': [
                {'AttributeName': 'FILE_NAME', 'AttributeType': 'S'},
                {'AttributeName': 'CRUISE_NAME', 'AttributeType': 'S'}
            ],
            'BillingMode': 'PAY_PER_REQUEST',
            'Tags': [
                {
                    'Key': 'project',
                    'Value': 'echofish'
                },
                {
                    'Key': 'created',
                    'Value': datetime.now().isoformat(timespec="seconds") + "Z"
                }
            ],
        }
        # TODO: create_table returns a dict for validation
        print('Creating table...')
        dynamodb.create_table(**params)
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=table_name)
        print(f"table: {table_name} created")
        # TODO: TEMPORARY — MOVE TO ORCHESTRATOR
    else:
        print('Table exists already.')


#####################################################################
def write_to_table(
        prefix: str,
        cruise_name: str,
        sensor_name: str,
        ship_name: str,
        file_name: str,
        zarr_bucket: str,
        zarr_path: str,
        min_echo_range: float,
        max_echo_range: float,
        num_ping_time_dropna: int,
        start_time: str,
        end_time: str,
        pipeline_status: str,
        frequencies: list,
        channels: list,
) -> None:
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = boto3.Session().client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
    try:
        response = dynamodb.put_item(  # TODO: verify status_code['ResponseMetadata']['HTTPStatusCode'] == 200
            TableName=table_name,
            Item={
                'FILE_NAME': {'S': file_name},
                'SHIP_NAME': {'S': ship_name},
                'CRUISE_NAME': {'S': cruise_name},
                'SENSOR_NAME': {'S': sensor_name},
                'ZARR_BUCKET': {'S': zarr_bucket},
                'ZARR_PATH': {'S': zarr_path},
                'MIN_ECHO_RANGE': {'N': str(np.round(min_echo_range, 4))},
                'MAX_ECHO_RANGE': {'N': str(np.round(max_echo_range, 4))},
                'NUM_PING_TIME_DROPNA': {'N': str(num_ping_time_dropna)},
                'START_TIME': {'S': start_time},
                'END_TIME': {'S': end_time},
                'PIPELINE_TIME': {'S': datetime.now().isoformat(timespec="seconds") + "Z"},
                'PIPELINE_STATUS': {'S': pipeline_status},
                'FREQUENCIES': {'L': [{'N': str(i)} for i in frequencies]},
                'CHANNELS': {'L': [{'S': i} for i in channels]},
            }
        )
        status_code = response['ResponseMetadata']['HTTPStatusCode']
        assert (status_code == 200), "Unable to update dynamodb table"
    except Exception as e:
        print(f"Error updating table: {e}")


#####################################################################
def set_processing_status(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
        file_name: str,  # Hash
        new_status: str,
) -> None:
    # Updates PIPELINE_STATUS via new_status value
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = boto3.Session().client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
    response = dynamodb.put_item(  # TODO: verify status_code['ResponseMetadata']['HTTPStatusCode'] == 200
        TableName=table_name,
        Item={
            'FILE_NAME': {'S': file_name},  # HASH
            'SHIP_NAME': {'S': ship_name},
            'CRUISE_NAME': {'S': cruise_name},
            'SENSOR_NAME': {'S': sensor_name},  # RANGE
            'PIPELINE_TIME': {'S': datetime.now().isoformat(timespec="seconds") + "Z"},
            'PIPELINE_STATUS': {'S': new_status},
        }
    )
    status_code = response['ResponseMetadata']['HTTPStatusCode']
    assert(status_code == 200), "Unable to update dynamodb table"


def update_processing_status(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
        file_name: str,  # Hash
        new_status: str,
) -> None:
    # Updates PIPELINE_STATUS via new_status value
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = boto3.Session().client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
    response = dynamodb.put_item(  # TODO: verify status_code['ResponseMetadata']['HTTPStatusCode'] == 200
        TableName=table_name,
        Item={
            'FILE_NAME': {'S': file_name},  # HASH
            'CRUISE_NAME': {'S': cruise_name}, # RANGE
            'PIPELINE_TIME': {'S': datetime.now().isoformat(timespec="seconds") + "Z"},
            'PIPELINE_STATUS': {'S': new_status},
        }
    )
    status_code = response['ResponseMetadata']['HTTPStatusCode']
    assert(status_code == 200), "Unable to update dynamodb table"

#####################################################################
def get_processing_status(
        prefix: str,
        ship_name: str,
        cruise_name: str,  # Range
        sensor_name: str,
        file_name: str,  # Hash
) -> str:
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = boto3.Session().client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
    response = dynamodb.get_item(
        TableName=table_name,
        Key={
            'FILE_NAME': {'S': file_name},  # Partition Key
            'CRUISE_NAME': {'S': cruise_name},  # Sort Key
        },
        AttributesToGet=['PIPELINE_STATUS']
    )
    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        if 'Item' in response:
            return response['Item']['PIPELINE_STATUS']['S']  # PROCESSING or SUCCESS
        else:
            return 'NONE'


#####################################################################
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


#####################################################################
def get_gps_data(
        echodata: ep.echodata.echodata.EchoData
) -> tuple:
    """Extracts GPS coordinate information from the NMEA datagrams
    using echodata object. Note: with len(nmea_times) ≈ 14691, and
    len(sv_times) ≈ 9776, the higher frequency NMEA datagram measurements
    needs to be right-aligned to the sv_times. The alignment will often
    lead to missing values in the latitude/longitude coordinates. For more
    information on d

    Parameters
    ----------
    echodata : str
        A calibrated and computed echodata object.

    Returns
    -------
    GeoJSON and Lat-Lon Arrays : tuple
        GeoJSON string of the cruise coordinates aligned to the ping_time data.

    Notes
    -----
    See also: https://github.com/OSOceanAcoustics/echopype/issues/656#issue-1219104771
    """
    assert(
        'latitude' in echodata.platform.variables and 'longitude' in echodata.platform.variables
    ), "Problem: GPS coordinates not found in echodata."
    latitude = echodata.platform.latitude.values
    longitude = echodata.platform.longitude.values  # len(longitude) == 14691
    # RE: time coordinates: https://github.com/OSOceanAcoustics/echopype/issues/656#issue-1219104771
    assert(
        'time1' in echodata.platform.variables and 'time1' in echodata.environment.variables
    ), "Problem: Time coordinate not found in echodata."
    # 'nmea_times' are times from the nmea datalogger associated with GPS
    nmea_times = echodata.platform.time1.values  # len(nmea_times) == 14691
    # 'time1' are times from the echosounder associated with transducer measurement
    time1 = echodata.environment.time1.values  # len(sv_times) == 9776
    # Align 'sv_times' to 'nmea_times'
    assert(
        np.all(time1[:-1] <= time1[1:]) and np.all(nmea_times[:-1] <= nmea_times[1:])
    ), "Problem: NMEA time stamps are not sorted."
    # find the indices where 'v' can be inserted into 'a'
    indices = np.searchsorted(a=nmea_times, v=time1, side="right") - 1
    #
    lat = latitude[indices]
    lat[indices < 0] = np.nan  # values recorded before indexing are set to nan
    lon = longitude[indices]
    lon[indices < 0] = np.nan
    assert(
            np.all(lat[~np.isnan(lat)] >= -90.) and np.all(lat[~np.isnan(lat)] <= 90.)
    ), "Problem: Data falls outside GPS bounds!"
    # https://osoceanacoustics.github.io/echopype-examples/echopype_tour.html
    gps_df = pd.DataFrame({'latitude': lat, 'longitude': lon, 'time1': time1}).set_index(['time1'])
    gps_gdf = geopandas.GeoDataFrame(
        gps_df,
        geometry=geopandas.points_from_xy(gps_df['longitude'], gps_df['latitude']),
        crs="epsg:4326"
    )
    # GeoJSON FeatureCollection with IDs as "time1"
    geo_json = gps_gdf.to_json()
    return geo_json, lat, lon


#####################################################################
def write_geojson_to_file(
        path: str,
        data: str
) -> None:
    """Write the GeoJSON file inside the Zarr store folder. Note that the
    file is not a technical part of the store, this is more of a hack
    to help pass the data along to the next processing step.

    Parameters
    ----------
    path : str
        The path to a local Zarr store where the file will be written.
    data : str
        A GeoJSON Feature Collection to be written to output file.

    Returns
    -------
    None : None
        No return value.
    """
    with open(os.path.join(path, 'geo.json'), "w") as outfile:
        outfile.write(data)


# {
# "prefix": "rudy",
# "ship_name": "Henry_B._Bigelow",
# "cruise_name": "HB0707",
# "sensor_name": "EK60",
# "input_bucket": "noaa-wcsd-pds",
# "output_bucket": "noaa-wcsd-zarr-pds",
# "input_file": "D20070711-T182032.raw"
# }

def main(
        prefix: str='rudy',
        ship_name: str='Henry_B._Bigelow',
        cruise_name: str='HB0707',
        sensor_name: str='EK60',
        input_bucket: str="noaa-wcsd-pds",
        output_bucket: str="noaa-wcsd-zarr-pds",
        #input_file: str="D20070711-T182032.raw"
        #input_file: str="D20070712-T152416.raw"
        input_file_name: str="D20070711-T182032.raw",  # TODO: integrate this...
) -> None:
    """This Lambda reads a raw Echosounder file from a s3 location. Calibrates
    & computes the Sv intensity values and then generates a Zarr store from the
    data. Adds a supplementary GeoJSON file to Zarr store and writes all the data
    out to a specified bucket. The processing status is updated in a cruise level
    curated DynamoDB.

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
    input_bucket : str
        Bucket where raw files are read from, e.g. AWS noaa-wcsd-pds bucket.
    output_bucket : str
        Bucket where files are written to. Can be the NOAA NODD bucket if the
        proper credentials are provided.
    input_file_name : str
        The specific file to be processed, e.g. D20070711-T182032.raw.

    Returns
    -------
    None : None
        None
    """
    #################################################################
    # AWS Lambda requires writes only in /tmp directory
    os.chdir(TEMPDIR) # TODO: PUT BACK
    print(os.getcwd())
    #################################################################
    # reading from public bucket right now
    # TODO: move to orchestrator
    raw_files = get_s3_files(
        bucket_name=input_bucket,
        sub_prefix=os.path.join("data", "raw", ship_name, cruise_name, sensor_name),
        file_suffix=FILE_SUFFIX,
    )
    #################################################################
    create_table(  # TODO: remove this in the future
        prefix=prefix,
        ship_name=ship_name,
        cruise_name=cruise_name,
        sensor_name=sensor_name
    )
    #################################################################
    #raw_file = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070711-T182032.raw'
    #raw_file = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070712-T152416.raw'
    for raw_file in raw_files:
        print(f"Processing raw_file: {raw_file}")
        row_split = raw_file.split(os.sep)
        # { ship: 'Okeanos_Explorer', cruise_name: 'EX1608', sensor_name: 'EK60', file_name: 'D20070711-T182032.raw' }
        ship_name, cruise_name, sensor_name, file_name = row_split[-4:]
        zarr_prefix = os.path.join("level_1", ship_name, cruise_name, sensor_name)
        store_name = f"{os.path.splitext(file_name)[0]}.zarr"
        #
        processing_status = get_processing_status(
            prefix=prefix,
            ship_name=ship_name,
            sensor_name=sensor_name,
            file_name=file_name,
            cruise_name=cruise_name
        )
        if processing_status == PIPELINE_STATUS.SUCCESS.value and not OVERWRITE:
            print('Already processed as SUCCESS, skipping...')  # TODO: change continue to 'return'
            continue
        set_processing_status(
            prefix=prefix,
            ship_name=ship_name,
            cruise_name=cruise_name,
            sensor_name=sensor_name,
            file_name=file_name,
            new_status=PIPELINE_STATUS.PROCESSING.value,
        )
        #################################################################
        delete_all_local_raw_and_zarr_files()
        download_raw_file(input_bucket=input_bucket, raw_file=raw_file)
        os.listdir()
        #################################################################
        print(f'Opening raw: {file_name}')
        # TODO: "use_swap" creates file in the users home directory
        echodata = ep.open_raw(file_name, sonar_model=sensor_name)  # TODO: "use_swap=True"
        delete_all_local_raw_and_zarr_files()
        #################################################################
        print('Compute volume backscattering strength (Sv) from raw data.')
        ds_Sv = ep.calibrate.compute_Sv(echodata)
        frequencies = echodata.environment.frequency_nominal.values
        #################################################################
        # Get GPS coordinates
        gps_data, lat, lon = get_gps_data(echodata=echodata)
        #################################################################
        zarr_path = os.path.join(zarr_prefix, store_name)
        # min_echo_range = float(np.nanmin(ds_Sv.echo_range.values[np.nonzero(ds_Sv.echo_range.values)]))
        min_echo_range = np.nanmin(np.diff(ds_Sv.echo_range.values))  # TODO: change to min_depth_diff
        max_echo_range = float(np.nanmax(ds_Sv.echo_range))
        num_ping_time_dropna = lat[~np.isnan(lat)].shape[0]  # symmetric to lon
        start_time = np.datetime_as_string(ds_Sv.ping_time.values[0], unit='ms') + "Z"
        end_time = np.datetime_as_string(ds_Sv.ping_time.values[-1], unit='ms') + "Z"
        channels = list(ds_Sv.channel.values)
        #################################################################
        # Create the zarr store
        ds_Sv.to_zarr(store=store_name)
        #################################################################
        print('Note: Adding GeoJSON inside Zarr store')
        write_geojson_to_file(path=store_name, data=gps_data)
        #################################################################
        # Verify file counts match
        file_count = get_file_count(store_name=store_name)
        raw_zarr_files = get_s3_files(
            bucket_name=output_bucket,
            sub_prefix=os.path.join(zarr_prefix, store_name),
            access_key_id=os.getenv('ACCESS_KEY_ID'),
            secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
        )
        #################################################################
        # Check if files exist
        if len(raw_zarr_files) == file_count and not OVERWRITE:
            # if PROCESSING but there are already files there and OVERWRITE is false
            print(f'objects: {store_name} already exist in {output_bucket} with proper count {file_count}.')
            write_to_table(
                prefix=prefix,
                cruise_name=cruise_name,
                sensor_name=sensor_name,
                ship_name=ship_name,
                file_name=file_name,
                zarr_bucket=output_bucket,
                zarr_path=zarr_path,
                min_echo_range=min_echo_range,  # TODO: change to diff
                max_echo_range=max_echo_range,
                num_ping_time_dropna=num_ping_time_dropna,
                start_time=start_time,
                end_time=end_time,
                pipeline_status=PIPELINE_STATUS.SUCCESS.value,
                frequencies=frequencies,
                channels=channels,
            )
            continue  # TODO: change continue to return
        if len(raw_zarr_files) > 0:
            print(f'{len(raw_zarr_files)} objects already exist at {store_name} in {output_bucket}. Deleting.')
            delete_remote_objects(
                raw_zarr_files=raw_zarr_files,
                output_bucket=output_bucket,
                access_key_id=os.getenv('ACCESS_KEY_ID'),
                secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
            )
        #
        print('Uploading files')
        upload_zarr_store_to_s3(  # TODO: Get time metrics for this...
            local_directory=store_name,
            bucket_name=output_bucket,
            object_prefix=zarr_prefix,
            access_key_id=os.getenv('ACCESS_KEY_ID'),
            secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
        )
        #################################################################
        # Verify # of remote zarr files equals # of local files
        raw_files_output_bucket = get_s3_files(
            bucket_name=output_bucket,
            sub_prefix=os.path.join(zarr_prefix, store_name),
            access_key_id=os.getenv('ACCESS_KEY_ID'),
            secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
        )
        if not len(raw_files_output_bucket) == file_count:
            raise
        delete_all_local_raw_and_zarr_files()
        #################################################################
        # Update table with stats
        write_to_table(
            prefix=prefix,
            cruise_name=cruise_name,
            sensor_name=sensor_name,
            ship_name=ship_name,
            file_name=file_name,
            zarr_bucket=output_bucket,
            zarr_path=zarr_path,
            min_echo_range=min_echo_range,
            max_echo_range=max_echo_range,
            num_ping_time_dropna=num_ping_time_dropna,
            start_time=start_time,
            end_time=end_time,
            pipeline_status=PIPELINE_STATUS.SUCCESS.value,
            frequencies=frequencies,
            channels=channels,
        )
        #
        print(f'Done processing {raw_file}')
        # TODO: write the remaining time to the DynamoDB table so we
        # can optimize for the best processing power
        #################################################################


#########################################################################
def lambda_handler(event: dict, context: dict) -> dict:
    logger.info(event)
    ### input from sqs ###
    #message = json.loads(event['Records'][0]['body'])
    ### input from sns ###
    message = json.loads(event['Records'][0]['Sns']['Message'])
    main(
        # prefix='rudy',
        # ship_name='Henry_B._Bigelow',
        # cruise_name='HB0707',
        # sensor_name='EK60',
        # input_bucket="noaa-wcsd-pds",
        # output_bucket="noaa-wcsd-zarr-pds",
        # input_file="D20070711-T182032.raw",
        prefix=message["prefix"],
        ship_name=message["ship_name"],
        cruise_name=message["cruise_name"],
        sensor_name=message["sensor_name"],
        input_bucket=message["input_bucket"],
        output_bucket=message["output_bucket"],
        input_file_name=message["input_file_name"],
    )
    return {"status": "success123"}

#########################################################################
