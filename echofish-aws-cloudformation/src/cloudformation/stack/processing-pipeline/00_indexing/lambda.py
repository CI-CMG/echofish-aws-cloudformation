#!/usr/bin/env python
"""
Bucket: https://ncei-wcsd-archive.s3.amazonaws.com/index.html
Duration 578579.80 ms --> 9.6 minutes
Max Memory Used: 3345 MB
Memory: 5000 MB, Storage: 1000 MB, Timeout 15 Minutes
Note: Requires Layer:
    AWSSDKPandas-Python39-Arm64, version 4, python3.9, arm64, arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python39-Arm64:4

(1) Run this to install needed files for arm. Note target folder:
    pip install --platform manylinux2014_armv7l --target=my-lambda-function-arm64 --implementation cp --python 3.9 --only-binary=:all: --upgrade botocore fsspec s3fs
(2) zip -r ../my-deployment-package-64.zip .
(3) aws --profile echofish s3 cp my-deployment-package-64.zip s3://noaa-wcsd-pds-index/
(4) create lambda

This file uses the calibration data found from https://docs.google.com/spreadsheets/d/1GpR1pu0ERfWlxDsQSDP9eOm94hRD_asy/edit#gid=1728447211
and stored in the bucket at "https://noaa-wcsd-pds-index.s3.amazonaws.com/calibrated_crusies.csv"

When run locally, all boto3.Sessions will need to have a profile enabled.
To enable the default profile have export AWS_DEFAULT_PROFILE=echofish set in your bashrc
"""

import os
import re
import boto3
# import logging
import numpy as np
import botocore
from botocore.config import Config
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

# https://ncei-wcsd-archive.s3.amazonaws.com/index.html
BUCKET_NAME = 'noaa-wcsd-pds'

session = boto3.Session()

dynamodb = session.client(service_name='dynamodb')

max_pool_connections = 64
client_config = botocore.config.Config(max_pool_connections=max_pool_connections)
s3 = session.client(service_name='s3', config=client_config)

# logging.basicConfig(level=logging.DEBUG)
# logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# Name of dynamoDB table to hold cruise level details
INDEX_EK60_TABLE_NAME = 'noaa-wcsd-pds-index-ek60'


def find_child_objects(
        sub_prefix: str
) -> list:
    # Given a cruise sub_prefix, return all the children objects
    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=BUCKET_NAME, Prefix=sub_prefix)
    objects = []
    for page in page_iterator:
        objects.extend(page['Contents'])
    return objects


def get_all_objects() -> pd.DataFrame:
    # Get all objects in data/raw/ s3 folder.
    # Returns pandas dataframe with ['Key', 'LastModified', 'ETag', 'Size', 'StorageClass']
    # Threaded by cruise to decrease time.
    print("getting all objects")
    cruises = []
    for ship in s3.list_objects(Bucket=BUCKET_NAME, Prefix='data/raw/', Delimiter='/').get('CommonPrefixes'):
        for cruise in s3.list_objects(Bucket=BUCKET_NAME, Prefix=ship.get('Prefix'), Delimiter='/').get(
                'CommonPrefixes'):
            cruises.append(cruise.get('Prefix'))
    all_objects = []
    with ThreadPoolExecutor(max_workers=max_pool_connections) as executor:
        futures = [executor.submit(find_child_objects, cruise) for cruise in cruises]
        for future in as_completed(futures):
            all_objects.extend(future.result())
    return pd.DataFrame(all_objects)


def get_subset_ek60_prefix(
        df: pd.DataFrame
) -> pd.DataFrame:
    # Returns all objects with 'EK60' in prefix of file path
    # Note that this can include 'EK80' data that are false-positives
    # in dataframe with ['key', 'filename', 'ship', 'cruise', 'sensor', 'size', 'date', 'datagram']
    print("getting subset of ek60 data by prefix")
    objects = []
    for row in df.itertuples():
        row_split = row[1].split(os.sep)
        if len(row_split) == 6:
            filename = os.path.basename(row[1])  # 'EX1608_EK60-D20161205-T040300.raw'
            if filename.endswith(".raw"):
                ship_name, cruise_name, sensor_name = row_split[2:5]  # 'Okeanos_Explorer', 'EX1608', 'EK60'
                if re.search("[D](\d{8})", filename) is not None and re.search("[T](\d{6})", filename) is not None:
                    # Parse date if possible e.g.: 'data/raw/Henry_B._Bigelow/HB1006/EK60/HBB-D20100723-T025105.raw'
                    # and 'data/raw/Henry_B._Bigelow/HB1802/EK60/D20180513-T150250.raw'
                    date_substring = re.search("[D](\d{8})", filename).group(1)
                    time_substring = re.search("[T](\d{6})", filename).group(1)
                    date_string = datetime.strptime(f'{date_substring}{time_substring}', '%Y%m%d%H%M%S')
                else:  # otherwise use current date
                    date_string = f"{datetime.utcnow().isoformat()[:19]}Z"
                objects.append(
                    {
                        'KEY': row[1],
                        'FILENAME': filename,
                        'SHIP': ship_name,
                        'CRUISE': cruise_name,
                        'SENSOR': sensor_name,
                        'SIZE': row[2],
                        'DATE': date_string,
                        'DATAGRAM': None
                    }
                )
    return pd.DataFrame(objects)


def scan_datagram(select_key: str) -> list:
    # Reads the first 8 bytes of S3 file. Used to determine if ek60 or ek80
    # Note: uses boto3 session instead of boto3 client: https://github.com/boto/boto3/issues/801
    # select_key = 'data/raw/Albatross_Iv/AL0403/EK60/L0005-D20040302-T200108-EK60.raw'
    session_thread_pool = boto3.Session()  # remove for lambda
    s3_thread_pool = session_thread_pool.resource(service_name='s3', config=client_config)
    obj = s3_thread_pool.Object(bucket_name=BUCKET_NAME, key=select_key)  # XML0
    first_datagram = obj.get(Range='bytes=3-7')['Body'].read().decode().strip('\x00')
    return [{'KEY': select_key, 'DATAGRAM': first_datagram}]


def get_subset_datagrams(df: pd.DataFrame) -> list:
    print("getting subset of datagrams")
    select_keys = list(df[['KEY', 'CRUISE']].drop_duplicates(subset='CRUISE')['KEY'].values)
    all_datagrams = []
    with ThreadPoolExecutor(max_workers=max_pool_connections) as executor:
        futures = [executor.submit(scan_datagram, select_key) for select_key in select_keys]
        for future in as_completed(futures):
            all_datagrams.extend(future.result())
    return all_datagrams


def get_ek60_objects(
        df: pd.DataFrame,
        subset_datagrams: list
) -> pd.DataFrame:
    # for each key write datagram value to all other files in same cruise
    for subset_datagram in subset_datagrams:
        if subset_datagram['DATAGRAM'] == 'CON0':
            select_cruise = df.loc[df['KEY'] == subset_datagram['KEY']]['CRUISE'].iloc[0]
            df.loc[df['CRUISE'] == select_cruise, ['DATAGRAM']] = subset_datagram['DATAGRAM']
    return df.loc[df['DATAGRAM'] == 'CON0']


def create_table(
        table_name: str = INDEX_EK60_TABLE_NAME
) -> None:
    params = {
        'TableName': table_name,
        'KeySchema': [
            {'AttributeName': 'CRUISE', 'KeyType': 'HASH'},
            {'AttributeName': 'SHIP', 'KeyType': 'RANGE'}
        ],
        'AttributeDefinitions': [
            {'AttributeName': 'CRUISE', 'AttributeType': 'S'},
            {'AttributeName': 'SHIP', 'AttributeType': 'S'}
        ],
        'BillingMode': 'PAY_PER_REQUEST',
        'Tags': [
            {
                'Key': 'project',
                'Value': 'echofish'
            },
        ],
    }
    # TODO: create_table returns a dict for validation
    table = dynamodb.create_table(**params)
    waiter = dynamodb.get_waiter('table_exists')
    waiter.wait(TableName=table_name)
    print(f"table: {table_name} created")


def delete_table(
        table_name: str = INDEX_EK60_TABLE_NAME
) -> None:
    # Attempts to delete an existing table.
    try:
        dynamodb.delete_table(TableName=table_name)
        waiter = dynamodb.get_waiter('table_not_exists')
        waiter.wait(TableName=table_name)
        print(f"table: {table_name} deleted")
    except dynamodb.exceptions.ClientError as err:
        # logger.error(
        #     "Could not delete table. Reason: %s: %s",
        #     err.response['Error']['Code'], err.response['Error']['Message']
        # )
        raise err
    except dynamodb.exceptions.ParamValidationError as error:
        raise ValueError('The parameters provided are incorrect: {}'.format(error))


def get_calibration_information(
        calibration_bucket: str = "noaa-wcsd-pds-index",
        calibration_key: str = "calibrated_crusies.csv",
) -> pd.DataFrame:
    # Calibration data generated by Chuck currently located here:
    #      https://noaa-wcsd-pds-index.s3.amazonaws.com/calibrated_crusies.csv
    response = s3.get_object(Bucket=calibration_bucket, Key=calibration_key)
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    calibration_status = pd.DataFrame(columns=["DATASET_NAME", "INSTRUMENT_NAME", "CAL_STATE"])
    if status == 200:
        calibration_status = pd.read_csv(response.get("Body"))
        calibration_status['DATASET_NAME'] = calibration_status['DATASET_NAME'].apply(lambda x: x.split('_EK60')[0])
        # Note: Data are either:
        #      [1] Calibrated w/ calibration data
        #      [2] Calibrated w/o calibration data
        #      [3] uncalibrated
        calibration_status['CAL_STATE'] = calibration_status['CAL_STATE'].apply(lambda x: x.find('Calibrated') >= 0)
    else:
        print(f"Unsuccessful S3 get_object response. Status - {status}")
    return calibration_status


def main():
    start = datetime.now()  # used for benchmarking
    # Get all object in public dataset bucket
    all_objects = get_all_objects()
    #
    subset_ek60_by_prefix = get_subset_ek60_prefix(
        df=all_objects[all_objects['Key'].str.contains('EK60')][['Key', 'Size']]
    )
    subset_datagrams = get_subset_datagrams(df=subset_ek60_by_prefix)
    ek60_objects = get_ek60_objects(subset_ek60_by_prefix, subset_datagrams)
    print(start)  # 1:26:57 to 1:39:??
    #
    current_tables = dynamodb.list_tables()
    if INDEX_EK60_TABLE_NAME in current_tables['TableNames']:
        print('deleting existing table')
        delete_table(table_name=INDEX_EK60_TABLE_NAME)

    # create new index table
    create_table(table_name=INDEX_EK60_TABLE_NAME)
    calibration_status = get_calibration_information()
    #
    # TODO: melt calibration_status with
    # ek60_objects['CALIBRATED'] = np.repeat(False, ek60_objects.shape[0])
    # cruises = list(set(ek60_objects['CRUISE']))
    # for i in cruises:
    #     print(i)
    #     if i in list(calibration_status['DATASET_NAME']):
    #         ek60_objects.loc[ek60_objects['CRUISE'] == i, 'CALIBRATED'] = True
    # ek60_objects['CALIBRATED'].value_counts()
    #
    cruise_names = list(set(ek60_objects['CRUISE']));
    cruise_names.sort()
    for cruise_name in cruise_names:  # ~322 cruises
        cruise_data = ek60_objects.groupby('CRUISE').get_group(cruise_name)
        ship = cruise_data['SHIP'].iloc[0]
        sensor = cruise_data['SENSOR'].iloc[0]
        datagram = cruise_data['DATAGRAM'].iloc[0]
        file_count = cruise_data.shape[0]
        total_size = np.sum(cruise_data['SIZE'])
        calibrated = cruise_name in calibration_status['DATASET_NAME'].unique()  # ~276 entries
        start_date = np.min(cruise_data['DATE']).isoformat(timespec="seconds") + "Z"
        end_date = np.max(cruise_data['DATE']).isoformat(timespec="seconds") + "Z"
        #
        dynamodb.put_item(  # TODO: verify status_code['ResponseMetadata']['HTTPStatusCode'] == 200
            TableName=INDEX_EK60_TABLE_NAME,
            Item={
                'CRUISE': {'S': cruise_name},
                'SHIP': {'S': ship},
                'SENSOR': {'S': sensor},
                'DATAGRAM': {'S': datagram},
                'FILE_COUNT': {'N': str(file_count)},
                'TOTAL_SIZE': {'N': str(total_size)},  # 'SIZE_BYTES'
                'CALIBRATED': {'S': str(calibrated)},
                'START_DATE': {'S': start_date},
                'END_DATE': {'S': end_date},
                # 'STATUS': {'S': _}
            }
        )
    end = datetime.now()  # used for benchmarking
    print(start)
    print(end)


def handler(event, context):
    print(f"total cpus: {os.cpu_count()}")
    main()
    print('done')
