"""Feature engineers the abalone dataset."""
import traceback
import argparse
import logging
import pathlib
import subprocess
import sys
import json

import boto3
from botocore.config import Config

# To easily add packages at runtime from codeartifact, you can use this method. A more graceful way is to install packages in
# a container and use that container as the processing container.
# @todo adjust hardcoded values into fetching from ssm parameters.
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
install("snowflake-connector-python==3.0.3")
# install("snowflake-snowpark-python==1.4.0") Needs Python3.8.*
install("snowflake-sqlalchemy==1.4.7")
install("sqlalchemy==1.4.47")


import awswrangler as wr
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

import numpy as np
import pandas as pd
import snowflake.connector
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder

feature_columns_names = [
    "sex",
    "length",
    "diameter",
    "height",
    "whole_weight",
    "shucked_weight",
    "viscera_weight",
    "shell_weight",
]
label_column = "rings"


def preprocess_abalone(abalone_dataset):
    logger.info("Reading downloaded data.")
    df = abalone_dataset

    logger.info("Defining transformers.")
    numeric_features = list(feature_columns_names)
    numeric_features.remove("sex")
    numeric_transformer = Pipeline(
        steps=[("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
    )
    categorical_features = ["sex"]
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="missing")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    preprocess = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, numeric_features),
            ("cat", categorical_transformer, categorical_features),
        ]
    )
    logger.info("Applying transforms.")
    y = df.pop("rings")
    X_pre = preprocess.fit_transform(df)
    y_pre = y.to_numpy().reshape(len(y), 1)
    X = np.concatenate((y_pre, X_pre), axis=1)
    logger.info("Splitting %d rows of data into train, validation, test datasets.", len(X))
    np.random.shuffle(X)
    return np.split(X, [int(0.7 * len(X)), int(0.85 * len(X))])

def fetch_pandas_old(cur, sql):
    """
    Putting this adapted method as fetch_pandas_all is failing inside here
    with a silent exit code I have not been able to identify.
    From doc:
        - fetch_pandas_all: https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api#fetch_pandas_all
        - fetch_pandas_old: https://docs.snowflake.com/developer-guide/python-connector/python-connector-pandas#migrating-to-pandas-dataframes
    """
    cur.execute(sql)
    cols = []
    rm = cur.description
    for rmi in rm:
        cols.append(rmi.name.lower())
    rows = 0
    dataset = pd.DataFrame()
    while True:
        dat = cur.fetchmany(500)
        if not dat:
            break   
        df = pd.DataFrame(dat, columns=cols)
        if dataset.empty:
            dataset = df
        else:
            dataset = pd.concat([dataset, df], ignore_index=True)
        rows += df.shape[0]
    return dataset

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

    logging.getLogger('snowflake.connector').setLevel(logging.DEBUG)

    logger.info("Starting preprocessing.")
    base_dir = "/opt/ml/processing"
    pathlib.Path(f"{base_dir}/data").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"{base_dir}/train").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"{base_dir}/test").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"{base_dir}/validation").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"{base_dir}/inference-test").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"{base_dir}/raw").mkdir(parents=True, exist_ok=True)
    #abalone_dataset = f"{base_dir}/input/athena-input.parquet"

    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=str, required=True)
    parser.add_argument("--executiontime", type=str, required=False)
    parser.add_argument("--custom-payload", type=str, required=False)
    parser.add_argument("--executiondate", type=str, required=False)
    parser.add_argument("--tenant", type=str, required=False)
    parser.add_argument("--database", type=str, required=True)
    parser.add_argument("--table", type=str, required=True)
    parser.add_argument("--filter", type=str, required=True)
    parser.add_argument("--start_datetime", type=str, required=True)
    parser.add_argument("--current_datetime", type=str, required=True)
    parser.add_argument("--pipeline_name", type=str, required=True)
    parser.add_argument("--pipeline_arn", type=str, required=True)
    parser.add_argument("--pipeline_execution_id", type=str, required=True)
    parser.add_argument("--pipeline_execution_arn", type=str, required=True)
    parser.add_argument("--bydf-param-name", type=str, required=False, default="")
    #parser.add_argument("--training_job_name", type=str, required=True)
    #parser.add_argument("--processing_job_name", type=str, required=True)

    args = parser.parse_args()
    logger.info(f"start_datetime:{args.start_datetime}")
    logger.info(f"current_datetime:{args.current_datetime}")
    logger.info(f"pipeline_name:{args.pipeline_name}")
    logger.info(f"pipeline_arn:{args.pipeline_arn}")
    logger.info(f"pipeline_execution_id:{args.pipeline_execution_id}")
    logger.info(f"pipeline_execution_arn:{args.pipeline_execution_arn}")
    logger.info(f"bydf_param_name:{args.bydf_param_name}")
    #logger.info(f"training_job_name:{args.training_job_name}")
    #logger.info(f"processing_job_name:{args.processing_job_name}")
    boto3.setup_default_session(region_name="eu-north-1")
    ssm = boto3.client('ssm', region_name="eu-north-1")
    env_type=ssm.get_parameter(Name='EnvType')['Parameter']['Value']

    if args.filter == "disabled":
        query_filter = ""
    else:
        query_filter = f'WHERE rings > {args.filter}'

    if args.bydf_param_name and exist_ssm_param(param_name=args.bydf_param_name):
        bydf = json.loads(ssm.get_parameter(Name=args.bydf_param_name)['Parameter']['Value'])
    else:
        logger.info(f"bydf_param_name {args.bydf_param_name} cannot be found")
        bydf = {}
    fetch_data_from = bydf.get("fetch_data_from", "athena")

    if fetch_data_from == "athena":
        abalone_dataset = wr.athena.read_sql_query(
            f'SELECT * FROM "{args.database}"."{args.table}" {query_filter};',
            database=args.database,
            workgroup= f"{env_type}-athena-workgroup",
            ctas_approach="False"
        )
    if fetch_data_from == "snowflake":
        ctx = snowflake.connector.connect(**bydf['connection_parameters'])
        query = f"""SELECT * FROM {args.table} {query_filter};"""
        cur = ctx.cursor()
        abalone_dataset = fetch_pandas_old(cur=cur, sql=query)

    if args.context == "training":

        pd.DataFrame(abalone_dataset).to_csv(f"{base_dir}/raw/raw.csv", header=False, index=False)
        train, validation, test = preprocess_abalone(abalone_dataset)
        logger.info("Writing out datasets to %s.", base_dir)
        pd.DataFrame(train).to_csv(f"{base_dir}/train/train.csv", header=False, index=False)
        pd.DataFrame(validation).to_csv(
            f"{base_dir}/validation/validation.csv", header=False, index=False
        )
        pd.DataFrame(test).to_csv(f"{base_dir}/test/test.csv", header=False, index=False)
    elif args.context == "inference":
        print("Some mock processing for now")
        
        print(f"execution time (UTC): {args.executiontime}")

        train, validation, test = preprocess_abalone(abalone_dataset)
        test_df = pd.DataFrame(test)
        first_column = test_df.columns[0]
        inference_data = test_df.drop([first_column], axis=1)
        pd.DataFrame(abalone_dataset).to_csv(f"{base_dir}/raw/raw.csv", header=False, index=False)
        pd.DataFrame(inference_data).to_csv(f"{base_dir}/inference-test/inference-data.csv", header=False, index=False)
    else:
        logger.info("missing context, allowed values are training or inference")
        sys.exit("missing supported context type")



