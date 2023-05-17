"""Postprocess"""
import argparse
import logging
import os
import pathlib
import requests
import tempfile
import json
import sys
import subprocess

import botocore
import boto3
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder

from botocore.config import Config

import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

boto3.setup_default_session(region_name="eu-north-1")

def auth_codeartifact(mlops_domain='cirrus-ml-ds-domain', domain_owner='813736554012', repository='cirrus-ml-ds-shared-repo',
                    region='eu-north-1'):
    # fetches temporary credentials with boto3 from codeartifact, creates the index_url for the pip config
    # and finally uses the index_url (url with token included) to update the global pip config
    # when pip install is run, this means that pip install will utilize codeartifact instead of trying to reach public pypi
    boto3_config = Config(
        region_name = 'eu-north-1',
        signature_version = 'v4',
        retries = {
            'max_attempts': 10,
            'mode': 'standard'
        }
    )
    client = boto3.client('codeartifact',config=boto3_config)
    codeartifact_token = client.get_authorization_token(
        domain=mlops_domain,
        domainOwner=domain_owner,
        durationSeconds=10000
    )
    codeartifact_token["authorizationToken"]
    pip_index_url = f'https://aws:{codeartifact_token["authorizationToken"]}@{mlops_domain}-{domain_owner}.d.codeartifact.{region}.amazonaws.com/pypi/{repository}/simple/'
    subprocess.run(["pip", "config", "set", "global.index-url", pip_index_url],
                   capture_output=True)

def install(package):
    command = ["pip", "install", package]
    with subprocess.Popen(command, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True) as p:
        for line in p.stdout:
            print(line, end='')

auth_codeartifact()
install("awswrangler")
install("snowflake-sqlalchemy==1.4.7")
install("sqlalchemy==1.4.47")

import awswrangler as wr
from sqlalchemy import create_engine
from snowflake.sqlalchemy import URL


def exist_ssm_param(param_name: str) -> bool:
    ssm = boto3.client('ssm', region_name='eu-north-1')

    try:
        response = ssm.get_parameter(
            Name=param_name
        )
        return True
    except ssm.exceptions.ParameterNotFound:
        pass
    return False


if __name__ == "__main__":

    logger.info(">>> Starting postprocessing.")
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=str, required=True)
    parser.add_argument("--triggerid", type=str, required=True)
    parser.add_argument("--inferenceoutput", type=str, required=True)
    parser.add_argument("--sourceaccount", type=str, required=True)
    parser.add_argument("--bydf-param-name", type=str, required=False, default="")
    args = parser.parse_args()
    
    print(args)

    ssm = boto3.client('ssm', region_name="eu-north-1")
    source_account=args.sourceaccount
    env_type=ssm.get_parameter(Name='EnvType')['Parameter']['Value']

    if args.bydf_param_name and exist_ssm_param(param_name=args.bydf_param_name):
        bydf = json.loads(ssm.get_parameter(Name=args.bydf_param_name)['Parameter']['Value'])

        if bydf['target'] == 'kinesis': # use data foundation kinesis setup
            source_env = env_type
            if env_type == "exp":
                source_env = "dev"

            team_name=ssm.get_parameter(Name='TeamName')['Parameter']['Value']
            STREAM_NAME = f"{team_name}-ml-integration"
            ASSUMED_ROLE = f"arn:aws:iam::{source_account}:role/{team_name}-{source_env}-ml-integration-role"

            sts_client = boto3.client('sts')
            assumed_role_object = sts_client.assume_role(
                RoleArn=ASSUMED_ROLE,
                RoleSessionName="ml-kinesis-access"
            )
            
            credentials = assumed_role_object['Credentials']
            session = boto3.session.Session(
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'],
                region_name="eu-north-1"
            )

            kinesis = session.client('kinesis')

            data = {}
            triggerid = str(uuid.uuid4())
            data['trigger_id'] = args.triggerid
            data['keys']=[f"{args.inferenceoutput}/inference-data.csv.out"]

            print(data)

            kinesis.put_record(
                        StreamName=STREAM_NAME,
                        Data=json.dumps(data),
                        PartitionKey=triggerid)
        if bydf['target'] == "eb":
            account_id = boto3.client('sts').get_caller_identity().get('Account')
            events = boto3.client('events', region_name='eu-north-1')

            event_bus_arn = f'arn:aws:events:eu-north-1:{account_id}:event-bus/ml-event-bus'

            event = {
                'Source': 'sagemaker',
                'DetailType': 'sagemaker-pipeline-success-execution',
                'Detail': json.dumps({
                    "currentPipelineExecutionStatus": "Success",
                    "triggerId": args.triggerid,
                    "pipeline": bydf['pipeline']
                }),
                'EventBusName': event_bus_arn
            }

            events.put_events(Entries=[event])
        if bydf['target'] == "snowflake":
            print(args.inferenceoutput)
            df = wr.s3.read_csv(path=args.inferenceoutput)
            df.columns = ["id","date","result"]
            print(df)
            engine = create_engine(URL(**bydf['connection_parameters']))
            df.to_sql('inference_results', con=engine, index=False, if_exists='append')


    logger.info(">>> End postprocessing.")
