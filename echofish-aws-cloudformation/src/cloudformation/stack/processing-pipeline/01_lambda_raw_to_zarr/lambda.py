#!/usr/bin/env python

import os
import json
import glob
import shutil
import echopype as ep
import boto3
import botocore
import numpy as np
import pandas as pd
import geopandas
from datetime import datetime
from botocore.config import Config
from botocore.exceptions import ClientError
from enum import Enum

ENV = Enum("ENV", ["DEV", "PROD"])

session = boto3.Session()
max_pool_connections = 64
SECRET_NAME = "NOAA_WCSD_ZARR_PDS_BUCKET" # TODO: DON'T NEED HERE

client_config = botocore.config.Config(max_pool_connections=max_pool_connections)
transfer_config = boto3.s3.transfer.TransferConfig(
    max_concurrency=100,
    num_download_attempts=5,
    max_io_queue=100,
    use_threads=True,
    max_bandwidth=None
)

s3 = session.client(service_name='s3', config=client_config)  # good
FILE_SUFFIX = '.raw'
OVERWRITE = False
# SIMPLIFICATION_TOLERANCE = 0.001


def delete_all_local_raw_and_zarr_files():
    # Used to cleanse the system of any ephemeral files
    for i in ['*.raw*', '*.zarr']:
        for j in glob.glob(i):
            f'Deleting {j}'
            if os.path.isdir(j):
                shutil.rmtree(j, ignore_errors=True)
            elif os.path.isfile(j):
                os.remove(j)

def delete_remote(raw_zarr_files: list, output_bucket: str, s3_zarr_client):
    # Delete in groups of 100
    objects_to_delete = []
    for raw_zarr_file in raw_zarr_files:
        objects_to_delete.append({'Key': raw_zarr_file['Key']})
    # Delete in groups of 100 -- Boto3 constraint.
    for batch in chunks(objects_to_delete, 100):
        # print(f"0: {batch[0]}, -1: {batch[-1]}")
        deleted = s3_zarr_client.delete_objects(
            Bucket=output_bucket,
            Delete={
                "Objects": batch
            }
        )
        print(f"Deleted {len(deleted['Deleted'])} files")


def chunks(ll, n):
    # Yields successive n-sized chunks from ll.
    # Needed to delete files in groups of N
    for i in range(0, len(ll), n):
        yield ll[i:i + n]


# def check_object_exists(object_key: str) -> bool:
#     try:
#         s3.Object(WCSD_BUCKET_NAME, object_key).load()
#     except botocore.exceptions.ClientError as e:
#         if e.response['Error']['Code'] == "404":
#             # The object does not exist.
#             return False
#         else:
#             # Something else has gone wrong.
#             raise
#             return False
#     else:
#         return True


def find_child_objects(bucket_name: str, sub_prefix: str) -> list:
    # Find all objects for a given prefix string.
    # Returns list of strings.
    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=sub_prefix)
    objects = []
    for page in page_iterator:
        objects.extend(page['Contents'])
    return objects


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
                # s3 = session.client(service_name='s3', config=client_config)
                s3_client.upload_file(
                    Filename=local_path,
                    Bucket=bucket,
                    Key=s3_key,
                    Config=transfer_config
                )
            except ClientError as e:
                # logging.error(e)
                print(e)


def get_raw_files(
        bucket_name: str,
        sub_prefix: str,
        file_suffix: str = None
) -> list:
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
    except ClientError as err:
        print(f"Some problem was encountered: {err}")
    finally:
        return raw_files


########################################
# TODO: TEMPORARY — MOVE TO ORCHESTRATOR
def create_table(
        prefix: str,
        ship_name: str,
        cruise_name: str,
        sensor_name: str,
) -> None:
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    # TODO: TEMPORARY — MOVE TO ORCHESTRATOR
    dynamodb = session.client(service_name='dynamodb')
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
    frequencies: list,
    channels: list,
) -> None:
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = session.client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
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
            'PIPELINE_STATUS': {'S': 'SUCCESS'},
            'FREQUENCIES': {'L': [{'N': str(i)} for i in frequencies]},
            'CHANNELS': {'L': [{'S': i} for i in channels]},
        }
    )
    status_code = response['ResponseMetadata']['HTTPStatusCode']
    #print(f"Status code: {status_code}")
    assert (status_code == 200), "Unable to update dynamodb table"


def set_processing_status(
    prefix: str,
    ship_name: str,
    cruise_name: str,
    sensor_name: str,
    file_name: str,  # Hash
    new_status: str, # TODO: change to enum
) -> None:
    # Updates PIPELINE_STATUS via new_status value
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = session.client(service_name='dynamodb')
    table_name = f"{prefix}_{ship_name}_{cruise_name}_{sensor_name}"
    response = dynamodb.put_item(  # TODO: verify status_code['ResponseMetadata']['HTTPStatusCode'] == 200
        TableName=table_name,
        Item={
            'FILE_NAME': {'S': file_name},  # HASH
            'SHIP_NAME': {'S': ship_name},
            'CRUISE_NAME': {'S': cruise_name},
            'SENSOR_NAME': {'S': sensor_name},  # RANGE
            'PIPELINE_TIME': {'S': datetime.now().isoformat(timespec="seconds") + "Z"},
            'PIPELINE_STATUS': {'S': new_status},  # TODO: change to enum
        }
    )
    status_code = response['ResponseMetadata']['HTTPStatusCode']
    assert(status_code == 200), "Unable to update dynamodb table"


def get_processing_status(
        prefix: str,
        ship_name: str,
        sensor_name: str,
        file_name: str,  # Hash
        cruise_name: str,
) -> None:
    # HASH: FILE_NAME, RANGE: SENSOR_NAME
    dynamodb = session.client(service_name='dynamodb')
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
            return response['Item']['PIPELINE_STATUS']['S'] # PROCESSING or SUCCESS
        else:
            return 'NONE'



def get_file_count(store_name: str):
    count = 0  # count number of local zarr files
    for subdir, dirs, files in os.walk(store_name):
        count += len(files)
    return count


# min_echo_range = np.nanmin(ds_Sv.echo_range.values[np.nonzero(ds_Sv.echo_range.values)])
# max_echo_range = np.nanmax(ds_Sv.echo_range)  # WRITE TO DYNAMODB
# num_channel = ds_Sv.channel.shape[0]
# num_ping_time = ds_Sv.ping_time.shape[0]

def main(
        #
        environment: str='DEV',
        prefix: str='rudy',
        ship_name: str='Henry_B._Bigelow',
        cruise_name: str='HB0707',
        sensor_name: str='EK60'
) -> None:
    #################################################################
    # if ENV[environment] is ENV.PROD:
    # INPUT_BUCKET = "noaa-wcsd-zarr-pds"
    # OUTPUT_BUCKET = "noaa-wcsd-zarr-pds"
    INPUT_BUCKET = "noaa-wcsd-pds"
    OUTPUT_BUCKET = "noaa-wcsd-pds-index"
    #################################################################
    sub_prefix = os.path.join("data", "raw", ship_name, cruise_name, sensor_name)
    raw_files = get_raw_files(
        bucket_name=INPUT_BUCKET,
        sub_prefix=sub_prefix,
        file_suffix=FILE_SUFFIX,
    )
    # TODO: Coordinate file updates with dyanmoDB
    create_table(
        prefix=prefix,
        ship_name=ship_name,
        cruise_name=cruise_name,
        sensor_name=sensor_name
    )
    # TODO: don't need to loop, process single file at time
    for raw_file in raw_files:
        print(f"Processing: {raw_file}")
        row_split = raw_file.split(os.sep)
        ship_name, cruise_name, sensor_name, file_name = row_split[-4:]  # 'Okeanos_Explorer', 'EX1608', 'EK60'
        zarr_prefix = os.path.join("data", "raw", ship_name, cruise_name, sensor_name)
        store_name = f"{os.path.splitext(file_name)[0]}.zarr"
        #
        processing_status = get_processing_status(prefix=prefix, ship_name=ship_name, sensor_name=sensor_name, file_name=file_name, cruise_name=cruise_name)
        if processing_status == 'SUCCESS':
            print('Already processed, skipping...')
            continue
        set_processing_status(
            prefix=prefix,
            ship_name=ship_name,
            cruise_name=cruise_name,
            sensor_name=sensor_name,
            file_name=file_name,
            new_status="PROCESSING",
        )
        #################################################################
        delete_all_local_raw_and_zarr_files()
        #
        s3.download_file(
            Bucket=INPUT_BUCKET,
            Key=raw_file,
            Filename=os.path.basename(raw_file),
            Config=transfer_config
        )
        print(f'Opening raw: {file_name}')
        echodata = ep.open_raw(file_name, sonar_model=sensor_name)  # 'EK60'
        if os.path.exists(os.path.basename(raw_file)):
            print(f'Removing existing raw file: {os.path.basename(raw_file)}')
            os.remove(os.path.basename(raw_file))
        print('Compute volume backscattering strength (Sv) from raw data.')
        ds_Sv = ep.calibrate.compute_Sv(echodata)
        frequencies = echodata.environment.frequency_nominal.values
        assert(
            'latitude' in echodata.platform.variables and 'longitude' in echodata.platform.variables
        ), "GPS coordinates not found."
        latitude = echodata.platform.latitude.values
        longitude = echodata.platform.longitude.values  # len(longitude) == 14691
        # RE time coordinates: https://github.com/OSOceanAcoustics/echopype/issues/656#issue-1219104771
        nmea_times = echodata.platform.time1.values  # len(nmea_times) == 14691
        time1 = echodata.environment.time1.values  # len(sv_times) == 9776
        # Because of differences in measurement frequency, figure out where sv_times match up to nmea_times
        assert(
            np.all(time1[:-1] <= time1[1:]) and np.all(nmea_times[:-1] <= nmea_times[1:])
        ), "NMEA time stamps are not sorted."
        indices = nmea_times.searchsorted(time1, side="right") - 1
        lat = latitude[indices]
        lat[indices < 0] = np.nan  # values recorded before indexing are set to nan
        lon = longitude[indices]
        lon[indices < 0] = np.nan
        # https://osoceanacoustics.github.io/echopype-examples/echopype_tour.html
        gps_df = pd.DataFrame({'latitude': lat, 'longitude': lon, 'time1': time1}).set_index(['time1'])
        gps_gdf = geopandas.GeoDataFrame(
            gps_df,
            geometry=geopandas.points_from_xy(gps_df['longitude'], gps_df['latitude']),
            crs="epsg:4326"
        )
        # Returns a FeatureCollection with IDs as "time1"
        geo_json = gps_gdf.to_json()
        zarr_path = os.path.join(zarr_prefix, store_name)
        min_echo_range = float(np.nanmin(ds_Sv.echo_range.values[np.nonzero(ds_Sv.echo_range.values)]))
        max_echo_range = float(np.nanmax(ds_Sv.echo_range))
        num_ping_time_dropna = gps_df.dropna().shape[0]
        start_time = np.datetime_as_string(ds_Sv.ping_time.values[0], unit='ms') + "Z"
        end_time = np.datetime_as_string(ds_Sv.ping_time.values[-1], unit='ms') + "Z"
        channels = list(ds_Sv.channel.values)
        #
        if os.path.exists(store_name):
            print(f'Removing existing zarr directory: {store_name}')
            shutil.rmtree(store_name)
        print('Creating Zarr')
        #
        # TODO: will this crash if it doesn't write to /tmp directory
        #
        ds_Sv.to_zarr(store=store_name)
        print('Note: Adding GeoJSON inside Zarr store')
        with open(os.path.join(store_name, 'geo.json'), "w") as outfile:
            outfile.write(geo_json)
        file_count = get_file_count(store_name=store_name)
        #################################################################
        # if ENV[environment] is ENV.PROD:
        #     print("If PROD use external credential to write to noaa-wcsd-zarr-pds bucket")
        #     secret = get_secret(secret_name=SECRET_NAME)
        #     s3_zarr_client = boto3.client(
        #         service_name='s3',
        #         aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
        #         aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
        #     )
        # else:
        print("If DEV use regular credentials to write to dev bucket")
        s3_zarr_client = session.client(service_name='s3', config=client_config)
        #################################################################
        raw_zarr_files = get_raw_files(
            bucket_name=OUTPUT_BUCKET,
            sub_prefix=os.path.join(zarr_prefix, store_name)
        )
        if len(raw_zarr_files) == file_count and not OVERWRITE:
            # if PROCESSING but there are already files there and OVERWRITE is false
            print(f'objects: {store_name} already exist in {OUTPUT_BUCKET} with proper count {file_count}.')
            write_to_table(
                prefix=prefix,
                cruise_name=cruise_name,
                sensor_name=sensor_name,
                ship_name=ship_name,
                file_name=file_name,
                zarr_bucket=OUTPUT_BUCKET,
                zarr_path=zarr_path,
                min_echo_range=min_echo_range,
                max_echo_range=max_echo_range,
                num_ping_time_dropna=num_ping_time_dropna,
                start_time=start_time,
                end_time=end_time,
                frequencies=frequencies,
                channels=channels,
            )
            continue
        if len(raw_zarr_files) > 0:
            print(f'{len(raw_zarr_files)} objects already exist at {store_name} in {OUTPUT_BUCKET}. Deleting.')
            delete_remote(raw_zarr_files=raw_zarr_files, output_bucket=OUTPUT_BUCKET, s3_zarr_client=s3_zarr_client)
        #
        print('Uploading files')
        upload_files(
            local_directory=store_name,
            bucket=OUTPUT_BUCKET,
            object_prefix=zarr_prefix,
            s3_client=s3_zarr_client
        )
        # Verify number of remote zarr files.
        num_raw_files = len(get_raw_files(
            bucket_name=OUTPUT_BUCKET,
            sub_prefix=os.path.join(zarr_prefix, store_name)
        ))
        if not num_raw_files == file_count:
            raise
        if os.path.exists(store_name):
            print(f'Removing zarr directory: {store_name}')
            shutil.rmtree(store_name)
        #
        # Write to DynamoDB
        #
        write_to_table(
            prefix=prefix,
            cruise_name=cruise_name,
            sensor_name=sensor_name,
            ship_name=ship_name,
            file_name=file_name,
            zarr_bucket=OUTPUT_BUCKET,
            zarr_path=zarr_path,
            min_echo_range=min_echo_range,
            max_echo_range=max_echo_range,
            num_ping_time_dropna=num_ping_time_dropna,
            start_time=start_time,
            end_time=end_time,
            frequencies=frequencies,
            channels=channels,
        )
        #
        print(f'Done processing {raw_file}')


def lambda_handler(event: dict, context: dict) -> dict:
    print("Processing bucket: {event['bucket']}, key: {event['key']}.")
    message = "Processing bucket: {event['bucket']}, key: {event['key']}."
    main(
        environment=os.environ['ENV'],  # DEV or TEST
        prefix=os.environ['PREFIX'],    # unique to each cloudformation deployment
        ship_name=os.environ['SHIP'],
        cruise_name=os.environ['CRUISE'],
        sensor_name=os.environ['SENSOR']
    )
    return {'message': message}

######################################################################
# >>> echodata
# <EchoData: standardized raw data from Internal Memory>
# Top-level: contains metadata about the SONAR-netCDF4 file format.
# ├── Environment: contains information relevant to acoustic propagation through water.
# ├── Platform: contains information about the platform on which the sonar is installed.
# │   └── NMEA: contains information specific to the NMEA protocol.
# ├── Provenance: contains metadata about how the SONAR-netCDF4 version of the data were obtained.
# ├── Sonar: contains sonar system metadata and sonar beam groups.
# │   └── Beam_group1: contains backscatter data (either complex samples or uncalibrated power samples) and other...
# └── Vendor_specific: contains vendor-specific information about the sonar and the data.
# >>>
# >>> ds_Sv = ep.calibrate.compute_Sv(echodata)
# >>> ds_Sv
# <xarray.Dataset>
# Dimensions:                (channel: 2, range_sample: 2615, ping_time: 67007,
#                             filenames: 1, time3: 67007)
# Coordinates:
#   * channel                (channel) <U34 'GPT  18 kHz 00907203398a 2 ES18-11...
#   * range_sample           (range_sample) int64 0 1 2 3 ... 2611 2612 2613 2614
#   * ping_time              (ping_time) datetime64[ns] 2008-04-09T12:29:34.685...
#   * filenames              (filenames) int64 0
#   * time3                  (time3) datetime64[ns] 2008-04-09T12:29:34.6850001...
# Data variables:
#     Sv                     (channel, ping_time, range_sample) float64 -1.215 ...
#     echo_range             (channel, ping_time, range_sample) float64 0.0 ......
#     frequency_nominal      (channel) float64 1.8e+04 3.8e+04
#     sound_speed            (channel, ping_time) float64 1.494e+03 ... 1.494e+03
#     sound_absorption       (channel, ping_time) float64 0.002665 ... 0.009785
#     sa_correction          (ping_time, channel) float64 0.0 0.0 0.0 ... 0.0 0.0
#     gain_correction        (ping_time, channel) float64 22.9 21.5 ... 22.9 21.5
#     equivalent_beam_angle  (channel, ping_time) float64 -17.0 -17.0 ... -15.5
#     source_filenames       (filenames) <U74 's3://noaa-wcsd-pds/data/raw/Alba...
#     water_level            (channel, time3) float64 0.0 0.0 0.0 ... 0.0 0.0 0.0
# Attributes:
#     processing_software_name:     echopype
#     processing_software_version:  0.6.3
#     processing_time:              2023-03-14T20:21:18Z
#     processing_function:          calibrate.compute_Sv
######################################################################
