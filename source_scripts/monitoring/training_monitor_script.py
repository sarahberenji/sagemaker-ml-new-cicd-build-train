import os
import json
import logging
print(os.getcwd())

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
region = os.environ.get('Region', 'eu-north-1')

logger.info(f'region: {region}')

def postprocess_handler():
    #create empty violations file
    #needed due to ClientError: Cannot access S3 key:
    #mlops-dev-370702650160-eu-north-1-data/lifecycle/60d/ml-build-bronze-peter/d56f0e0/2023_02_08_09_59_31/p1033/output/training/processed/data-check/constraint_violations.json.
    #this file shouldnt be created when we are not doing data checks.
    #been in contact with support on Case ID 11941060181 in cirrus-ml-dev.
    #internal ticket created for sagemaker team to look into this
    #until resolved, manually addint an empty file with correct name.
    violations_file = "/opt/ml/processing/output/constraint_violations.json"

    data="{}"
    with open(violations_file, 'w') as f:
        json.dump(data, f, ensure_ascii=False)
