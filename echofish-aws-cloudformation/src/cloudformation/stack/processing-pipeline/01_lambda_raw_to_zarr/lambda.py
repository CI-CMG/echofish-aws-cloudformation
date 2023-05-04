#!/usr/bin/env python


# TODO: Ensure you don't process NOISE files somehow


import os
import json
import shutil
import echopype as ep
import boto3
import botocore
import numpy as np
import pandas as pd
import geopandas as gpd
from datetime import datetime
from botocore.config import Config
from botocore.exceptions import ClientError

session = boto3.Session()
max_pool_connections = 64
secret_name = "NOAA_WCSD_ZARR_PDS_BUCKET"

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
FILE_SUFFIX = '.raw'
OVERWRITE = False
SIMPLIFICATION_TOLERANCE = 0.001


def chunks(ll, n):
    # Yields successive n-sized chunks from ll.
    # Needed to delete files in groups of N
    for i in range(0, len(ll), n):
        yield ll[i:i + n]


def check_object_exists(object_key: str) -> bool:
    try:
        s3.Object(WCSD_BUCKET_NAME, object_key).load()
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            # The object does not exist.
            return False
        else:
            # Something else has gone wrong.
            raise
            return False
    else:
        return True


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
    # Returns [] if none are found or error encountered.
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


########################################
### TEMPORARY — MOVE TO ORCHESTRATOR ###
def create_table(
        ship: str,
        cruise: str,
        sensor: str,
        # table_name: str = CRUISE_TABLE_NAME  # 'noaa-wcsd-pds-cruise-ek60'
) -> None:
    dynamodb = session.client(service_name='dynamodb')
    table_name = f"{ship}_{cruise}_{sensor}"
    params = {
        'TableName': table_name,
        'KeySchema': [
            # Note: There can be multiple sensors for each cruise.
            {'AttributeName': 'FILENAME', 'KeyType': 'HASH'},
            {'AttributeName': 'START_TIME', 'KeyType': 'RANGE'}
        ],
        'AttributeDefinitions': [
            {'AttributeName': 'FILENAME', 'AttributeType': 'S'},
            {'AttributeName': 'START_TIME', 'AttributeType': 'S'}
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
    dynamodb.create_table(**params)
    waiter = dynamodb.get_waiter('table_exists')
    waiter.wait(TableName=table_name)
    print(f"table: {table_name} created")


def write_to_table(
        cruise_name: str,
        sensor_name: str,
        ship_name: str,
        filename: str,
        zarr_bucket: str,
        zarr_path: str,
        min_echo_range: float,
        max_echo_range: float,
        num_echo_range: int,
        num_channel: int,
        num_ping_time: int,
        num_ping_time_dropna: int,
        start_time: str,
        end_time: str,
        frequencies: list,
        channels: list,
) -> None:
    dynamodb = session.client(service_name='dynamodb')
    table_name = f"{ship_name}_{cruise_name}_{sensor_name}"
    dynamodb.put_item(  # TODO: verify status_code['ResponseMetadata']['HTTPStatusCode'] == 200
        TableName=table_name,
        Item={
            # 'CRUISE': {'S': cruise_name},
            # 'SENSOR': {'S': sensor_name},
            # 'SHIP': {'S': ship_name},
            'FILENAME': {'S': filename},
            'ZARR_BUCKET': {'S': zarr_bucket},
            'ZARR_PATH': {'S': zarr_path},
            'MIN_ECHO_RANGE': {'N': str(np.round(min_echo_range, 4))},
            'MAX_ECHO_RANGE': {'N': str(np.round(max_echo_range, 4))},
            'NUM_ECHO_RANGE': {'N': str(num_echo_range)},
            'NUM_CHANNEL': {'N': str(num_channel)},
            'NUM_PING_TIME': {'N': str(num_ping_time)},
            'NUM_PING_TIME_DROPNA': {'N': str(num_ping_time_dropna)},
            'START_TIME': {'S': start_time},
            'END_TIME': {'S': end_time},
            'PIPELINE_STATUS': {'S': 'SUCCESS'},
            'PIPELINE_TIME': {'S': datetime.now().isoformat(timespec="seconds") + "Z"},
            'FREQUENCIES': {'L': [{'N': str(i)} for i in frequencies]},
            'CHANNELS': {'L': [{'S': i} for i in channels]},
        }
    )


# min_echo_range = np.nanmin(ds_Sv.echo_range.values[np.nonzero(ds_Sv.echo_range.values)])
# max_echo_range = np.nanmax(ds_Sv.echo_range)  # WRITE TO DYNAMODB
# num_channel = ds_Sv.channel.shape[0]
# num_ping_time = ds_Sv.ping_time.shape[0]

def main(sub_prefix="data/raw/Henry_B._Bigelow/HB0707/EK60/"):
    # children = find_child_objects(bucket_name=WCSD_BUCKET_NAME, sub_prefix="data/raw/Okeanos_Explorer/EX1608/EK60/")
    # children = find_child_objects(bucket_name=WCSD_BUCKET_NAME, sub_prefix="data/raw/Henry_B._Bigelow/HB0707/EK60/")
    raw_files = get_raw_files(
        bucket_name=WCSD_BUCKET_NAME,
        sub_prefix=sub_prefix,
        file_suffix=FILE_SUFFIX,
    )
    # TODO: don't need to loop, process single file at time
    for raw_file in raw_files:
        print(raw_file)
        # E.g.: { 'raw_file': 'data/raw/Okeanos_Explorer/EX1608/EK60/EX1608_EK60-D20161205-T040300.raw' }
        # raw_file = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070712-T152416.raw'
        # raw_file = 'data/raw/Henry_B._Bigelow/HB0707/EK60/D20070712-T033431.raw'
        row_split = raw_file.split(os.sep)
        ship, cruise, sensor, filename = row_split[-4:]  # 'Okeanos_Explorer', 'EX1608', 'EK60'
        zarr_prefix = os.path.join("data", "raw", ship, cruise, sensor)
        zarr_directory = f"{os.path.splitext(filename)[0]}.zarr"
        # Check if Zarr store already exists in the destination bucket
        # total_objects = s3.list_objects_v2(
        #     Bucket=WCSD_ZARR_BUCKET_NAME,
        #     Prefix=os.path.join(zarr_prefix, zarr_directory)
        # )['KeyCount']
        # if total_objects > 0:
        #     print(f'objects: {zarr_directory} already exist in {WCSD_ZARR_BUCKET_NAME}.')
        #     continue  # Zarr Store already exists!
        s3.download_file(  # TODO: check if already exists?!
            Bucket=WCSD_BUCKET_NAME,
            Key=raw_file,
            Filename=os.path.basename(raw_file),
            Config=transfer_config
        )
        print(f'Open raw: {filename}')
        echodata = ep.open_raw(filename, sonar_model=sensor)  # 'EK60'
        if os.path.exists(os.path.basename(raw_file)):
            print(f'Removing existing raw file: {os.path.basename(raw_file)}')
            os.remove(os.path.basename(raw_file))
        # print('Compute volume backscattering strength (Sv) from raw data.')
        print(f'Computing Sv')
        ds_Sv = ep.calibrate.compute_Sv(echodata)
        print(ds_Sv)
        print(ds_Sv.Sv.shape)  # (4, 9776, 1302)
        #
        frequencies = echodata.environment.frequency_nominal.values
        latitude = echodata.platform.latitude.values
        longitude = echodata.platform.longitude.values  # len(longitude) == 14691
        nmea_times = echodata.platform.time1.values  # len(nmea_times) == 14691
        # np.min( np.diff(nmea_times) )  # TODO: verify non-negative
        time1 = echodata.environment.time1.values  # len(sv_times) == 9776
        # np.min( np.diff(sv_times) )  # TODO: verify non-negative
        # Because of differences in measurement frequency, figure out where sv_times match up to nmea_times
        indices = nmea_times.searchsorted(time1, side="right") - 1
        lat = latitude[indices]
        # np.count_nonzero(np.isnan(lat))
        lat[indices < 0] = np.nan  # values recorded before indexing are set to nan
        lon = longitude[indices]
        lon[indices < 0] = np.nan
        # https://osoceanacoustics.github.io/echopype-examples/echopype_tour.html
        # TODO: Write the gps_df geojson linestring to bucket for processing
        gps_df = pd.DataFrame({'latitude': lat, 'longitude': lon, 'time1': time1}).set_index(['time1'])
        gps_gdf = gpd.GeoDataFrame(
            gps_df,
            geometry=gpd.points_from_xy(gps_df['longitude'], gps_df['latitude']),
            crs="epsg:4326"
        )  # <-- NOTE this will be the actual width instead of ping_time
        # Returns a FeatureCollection with IDs as "time1"
        geojson = gps_gdf.to_json()
        # TODO: bookkeeping to keep track of missing values in lat/lon
        # TODO: bookkeeping to keep track of missing values in ds_Sv.Sv
        # ds = ep.calibrate.compute_Sv(ed)
        # ds.Sv.shape  # (3, 3202, 1322) <-- (freq, time, depth) <- TODO: is this always in this order?
        # len(ds.Sv.ping_time)  # 3202
        # time = ds.Sv.ping_time.values  # array([ 18000.,  38000.,  70000., 120000., 200000., 710000.])
        # echodata.top.attrs['title'] = "2017 Pacific Hake Acoustic Trawl Survey"
        #
        # TODO: Get attributes and pass along where needed downstream
        #
        # Get metrics for DynamoDB
        # zarr_bucket = WCSD_ZARR_BUCKET_NAME,
        zarr_path = os.path.join(zarr_prefix, zarr_directory)
        min_echo_range = float(np.nanmin(ds_Sv.echo_range.values[np.nonzero(ds_Sv.echo_range.values)]))
        max_echo_range = float(np.nanmax(ds_Sv.echo_range))
        num_echo_range = ds_Sv.range_sample.values.shape[0]
        num_channel = ds_Sv.channel.shape[0]
        num_ping_time = ds_Sv.ping_time.shape[0]
        num_ping_time_dropna = gps_df.dropna().shape[0]
        start_time = np.datetime_as_string(ds_Sv.ping_time.values[0], unit='ms') + "Z"
        end_time = np.datetime_as_string(ds_Sv.ping_time.values[-1], unit='ms') + "Z"
        channels = list(ds_Sv.channel.values)
        #
        if os.path.exists(zarr_directory):  # os.remove(zarr_filename)
            print(f'Removing existing zarr directory: {zarr_directory}')
            shutil.rmtree(zarr_directory)
        print('Creating Zarr')
        ds_Sv.to_zarr(store=zarr_directory)
        print('Note: Adding GeoJSON inside Zarr store')
        with open(os.path.join(zarr_directory, 'geo.json'), "w") as outfile:
            outfile.write(geojson)
        count = 0  # count number of local zarr files
        for subdir, dirs, files in os.walk(zarr_directory):
            count += len(files)
        # Create client for writing to NODD bucket.
        secret = get_secret(secret_name=secret_name)
        s3_zarr_client = boto3.client(
            service_name='s3',
            aws_access_key_id=secret['NOAA_WCSD_ZARR_PDS_ACCESS_KEY_ID'],
            aws_secret_access_key=secret['NOAA_WCSD_ZARR_PDS_SECRET_ACCESS_KEY'],
        )
        #
        # TODO: if num local files != num remote files
        raw_zarr_files = get_raw_files(
            bucket_name=WCSD_ZARR_BUCKET_NAME,
            sub_prefix=os.path.join(zarr_prefix, zarr_directory)
        )
        #  if not OVERWRITE:
        if len(raw_zarr_files) == count and not OVERWRITE:
            print(f'objects: {zarr_directory} already exist in {WCSD_ZARR_BUCKET_NAME} with proper count {count}.')
            continue  # TODO: change from continue to return statement
        if len(raw_zarr_files) > 0:
            print(f'Some objects arelready exist at {zarr_directory} in {WCSD_ZARR_BUCKET_NAME}. Deleting.')
            # TODO: delete all files in s3 bucket
            # Delete in groups of 100
            objects_to_delete = []
            for raw_zarr_file in raw_zarr_files:
                objects_to_delete.append({'Key': raw_zarr_file['Key']})
            # Delete in groups of 100 -- Boto3 constraint.
            for batch in chunks(objects_to_delete, 100):
                # print(f"0: {batch[0]}, -1: {batch[-1]}")
                deleted = s3_zarr_client.delete_objects(
                    Bucket=WCSD_ZARR_BUCKET_NAME,
                    Delete={
                        "Objects": batch
                    }
                )
                print(f"Deleted {len(deleted['Deleted'])} files")
        #
        print('Uploading files')
        upload_files(
            local_directory=zarr_directory,
            bucket=WCSD_ZARR_BUCKET_NAME,
            object_prefix=zarr_prefix,
            s3_client=s3_zarr_client
        )
        # Verify number of remote zarr files.
        num_raw_files = len(get_raw_files(
            bucket_name=WCSD_ZARR_BUCKET_NAME,
            sub_prefix=os.path.join(zarr_prefix, zarr_directory)
        ))
        if not num_raw_files == count:
            raise
        if os.path.exists(zarr_directory):  # os.remove(zarr_filename)
            print(f'Removing zarr directory: {zarr_directory}')
            shutil.rmtree(zarr_directory)
        #
        # Write to DynamoDB
        write_to_table(
            cruise_name=cruise,
            sensor_name=sensor,
            ship_name=ship,
            filename=filename,
            zarr_bucket=WCSD_ZARR_BUCKET_NAME,
            zarr_path=zarr_path,
            min_echo_range=min_echo_range,
            max_echo_range=max_echo_range,
            num_echo_range=num_echo_range,
            num_channel=num_channel,
            num_ping_time=num_ping_time,
            num_ping_time_dropna=num_ping_time_dropna,
            start_time=start_time,
            end_time=end_time,
            frequencies=frequencies,
            channels=channels,
        )
        #
        print('done processing raw_file')


# total_objects = s3.list_objects_v2(
#     Bucket=WCSD_ZARR_BUCKET_NAME,
#     Prefix='data/raw/Okeanos_Explorer_EX1608_EK60_EX1608_EK60-D20161207-T111909.raw.zarr'
# )['KeyCount']

if __name__ == '__main__':
    main()


def lambda_handler(event, context):
    json_region = os.environ['AWS_REGION']
    print("Processing bucket: {event['bucket']}, key: {event['key']}.")
    message = "Processing bucket: {event['bucket']}, key: {event['key']}."
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
