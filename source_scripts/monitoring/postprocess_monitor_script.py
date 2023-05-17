import os
import json
import re
import logging
from datetime import datetime
import boto3
from typing import Dict, List
from typing import Generator

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

import botocore
import argparse
def parse_arguments() -> argparse.Namespace :
    parser : argparse.ArgumentParser = argparse.ArgumentParser(description="Postprocessing to put data metrics to CW and adjust alarms")
    parser.add_argument(
        "--pipeline-name",
        type=str,
        required=True,
        help="name of the pipeline, used in the cloudwatch metrics as the dimension value for the dimension 'PipelineName'"
    )
    parser.add_argument(
        "--pipeline-arn",
        type=str,
        default="arn:aws:sagemaker:eu-north-1:370702650160:pipeline/ml-build-bronze-peter-inference-pipeline",
        required=True
    )
    parser.add_argument(
        "--sns-notification-arn",
        type=str,
        required=True,
        default="arn:aws:sns:eu-north-1:370702650160:dev-ml-notification",
        help="ARN for SNS to recive notifications from the cloudwatch alarms"
    )
    parser.add_argument(
        "--sns-custom-notification-arn",
        type=str,
        required=False,
        default="arn:aws:sns:eu-north-1:370702650160:test-notification-topic",
        help="ARN for SNS to recive notifications from the cloudwatch alarms"
    )
    parser.add_argument(
        "--update-rules",
        type=str,
        required=True,
        choices=['True',
                 'False'],
        help="boolean True/False regarding if the CW rules should be updated"
    )

    parser.add_argument(
        "--metrics-namespace",
        type=str,
        required=True,
        help="what metrics-namespace to use in cloudwatch"
    )
    parser.add_argument(
        "--framework",
        type=str,
        required=True,
        choices=['deequ'],
        help="what framework that was used to create the violations file (e.g. deequ)"

    )
    parser.add_argument(
        "--violations-file",
        type=str,
        required=False,
        default="/opt/ml/processing/monitoring/output/constraint_violations.json",
        help="local container path to violations file"
    )
    parser.add_argument(
        "--logging-level",
        type=str,
        required=False,
        choices=['CRITICAL',
                 'ERROR',
                 'WARNING',
                 'INFO',
                 'DEBUG',
                 'NOTSET'],
        default="INFO",
        help="local container path to violations file"
    )

    return parser.parse_args()

def print_args(args : argparse.Namespace) :
    for k in args.__dict__:
        print(k,":", args.__dict__[k])
        logger.info(f"{k} : {args.__dict__[k]}")

def set_logging_level(level):
    logging.basicConfig(level=logging._nameToLevel[level])

def load_file(violations_file : str ) -> Dict[str, List[Dict[str, any]]] :
    if os.path.isfile(violations_file):
        f = open(violations_file)
        violations : Dict[str, List[Dict[str, any]]] = json.load(f)
        logger.warning("Violations file detected")
        return violations
    else:
        logger.info("No violations file found. All good!")
        exit(0)
def cloudwatch_session() -> botocore.client.BaseClient:
    region = os.environ.get('Region', 'eu-north-1')
    cloudwatch : botocore.client.BaseClient = boto3.client("cloudwatch", region)
    return cloudwatch

def eventbridge_session() -> botocore.client.BaseClient:
    region = os.environ.get('Region', 'eu-north-1')
    eventbridge : botocore.client.BaseClient = boto3.client("events", region)
    return eventbridge


def update_alarms(cw : botocore.client.BaseClient, namespace : str, pipeline_name : str, sns_notification_arn : str) :
    update_alarm(cw=cw, namespace=namespace, pipeline_name= pipeline_name, metric_name='data_type_check', sns_notification_arn=sns_notification_arn)
    update_alarm(cw=cw, namespace=namespace, pipeline_name= pipeline_name, metric_name='completeness_check', sns_notification_arn=sns_notification_arn)
    update_alarm(cw=cw, namespace=namespace, pipeline_name= pipeline_name, metric_name='baseline_drift_check', sns_notification_arn=sns_notification_arn)
    update_alarm(cw=cw, namespace=namespace, pipeline_name= pipeline_name, metric_name='missing_column_check', sns_notification_arn=sns_notification_arn)
    update_alarm(cw=cw, namespace=namespace, pipeline_name= pipeline_name, metric_name='extra_column_check', sns_notification_arn=sns_notification_arn)
    update_alarm(cw=cw, namespace=namespace, pipeline_name= pipeline_name, metric_name='categorical_values_check', sns_notification_arn=sns_notification_arn)

def update_eventbridge_rules(
        eb : botocore.client.BaseClient,
        sns_notification_arn : str,
        pipeline_name : str,
        sns_custom_arn : str ,
        pipeline  : str
) :
    #@todo keep code that adds pipeline notification target on custom sns topic but comment it out
    add_pipeline_rule(
        eb,
        name=f"{pipeline_name}-failed", #pipeline_name failed
        status='["Failed"]',
        pipeline=pipeline
    )
    eventbridge_add_notification_targets(
        eb=eb,
        sns_notification_arn=sns_notification_arn,
        name = f"{pipeline_name}-failed",
        id = 'target-1'
    )

    add_pipeline_rule(
        eb,
        name=f"{pipeline_name}-multi-state",
        status='["Executing", "Failed"]',
        pipeline=pipeline
    )

    eventbridge_add_notification_targets(
        eb=eb,
        sns_notification_arn=sns_custom_arn,
        name = f"{pipeline_name}-multi-state",
        id = 'target-1'
    )

def eventbridge_add_notification_targets(
        eb,
        sns_notification_arn : str,
        id : str ,
        name : str
    ):
    eb.put_targets(
        Rule=name,
        Targets=[
            {
                'Id': id,
                'Arn': sns_notification_arn,
                "InputTransformer":
                    {
                        "InputPathsMap": {
                            "pipeline": "$.detail.pipelineArn",
                            "pipelineExecution": "$.detail.pipelineExecutionArn",
                            "state": "$.detail.currentPipelineExecutionStatus"
                        },
                        "InputTemplate": '{"pipeline": <pipeline>,"state": "<state>","pipelineExecution": "<pipelineExecution>", "customMessage" : "please login to the sagemaker studio for details"}'

                    }
            }
        ]
    )


def add_pipeline_rule(eb,
                      name,
                      status,
                      pipeline):
    eb.put_rule(
        Name=name,
        EventPattern=
        ('''
        {
            "detail-type": ["SageMaker Model Building Pipeline Execution Status Change"],
            "source": ["aws.sagemaker"],
            "detail": {
                 "pipelineArn": ["%s"]
                 ,
                 "currentPipelineExecutionStatus": %s
                }
        }
    ''' % (pipeline, status))

        ,
    )


def update_alarm(
        cw : botocore.client.BaseClient,
        namespace : str,
        pipeline_name : str,
        metric_name : str,
        sns_notification_arn : str) :
    cw.put_metric_alarm(
        AlarmName= f"{pipeline_name}-{metric_name}",
        ComparisonOperator='GreaterThanThreshold',
        EvaluationPeriods=1,
        MetricName=metric_name,
        Namespace=namespace,
        Period=60,
        Statistic='Sum',
        Threshold=0.0,
        ActionsEnabled=True,
        AlarmActions=[sns_notification_arn],
        AlarmDescription='Alarm when threshold is greater than 0',
        Dimensions=[
            {
                'Name': 'PipelineName',
                'Value': f'{pipeline_name}'
            },
        ]
    )

def deequ(feature: Dict[str, List[Dict[str, any]]], pipeline_name: str) -> Generator:
    """ interprets and formats deequ metrics
    https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor-interpreting-violations.html

    Schema for violations file from deequ
    {
    "violations": [{
      "feature_name" : "string",
      "constraint_check_type" :
              "data_type_check",
            | "completeness_check",
            | "baseline_drift_check",
            | "missing_column_check",
            | "extra_column_check",
            | "categorical_values_check"
      "description" : "string"
    }]
    }

    Types of Violations Monitored
    data_type_check
        If the data types in the current execution are not the same as in the baseline dataset, this violation is flagged.
        During the baseline step, the generated constraints suggest the inferred data type for each column.
        The monitoring_config.datatype_check_threshold parameter can be tuned to adjust the threshold on when it is flagged as a violation.

    completeness_check
        If the completeness (% of non-null items) observed in the current execution exceeds the threshold specified in completeness threshold specified per feature, this violation is flagged.
        During the baseline step, the generated constraints suggest a completeness value.

    baseline_drift_check
        If the calculated distribution distance between the current and the baseline datasets is
        more than the threshold specified in monitoring_config.comparison_threshold, this violation is flagged.

    missing_column_check
        If the number of columns in the current dataset is less than the number in the baseline dataset, this violation is flagged.

    extra_column_check
        If the number of columns in the current dataset is more than the number in the baseline, this violation is flagged.

    categorical_values_check
        If there are more unknown values in the current dataset than in the baseline dataset, this violation is flagged. This value is dictated by the threshold in monitoring_config.domain_content_threshold.

    """
    if "violations" in feature:
        for violation in feature["violations"]:
            if violation["constraint_check_type"] == "baseline_drift_check":
                desc = violation["description"]
                matches = re.search("distance: (.+) exceeds threshold: (.+)", desc)
                if matches:
                    logger.warning(f"Violation detected type: {violation['constraint_check_type']}  for feature {violation['feature_name']} and added to cloudwatch")
                    yield {
                        "metric_name": 'feature_baseline_drift',
                        "metric_value": float(matches.group(1)),
                        "metric_threshold": float(matches.group(2)),
                        "feature": f'{violation["feature_name"]}',
                        "pipeline_name": f'{pipeline_name}'
                    }
            else :
                logger.warning(f"Violation detected type: {violation['constraint_check_type']}  for feature {violation['feature_name']} and added to cloudwatch")
                yield {
                    "metric_name": violation["constraint_check_type"],
                    "metric_value": float(1),
                    "metric_threshold": float(1),
                    "feature": f'{violation["feature_name"]}',
                    "pipeline_name": f'{pipeline_name}'
                }
                    
def put_cloudwatch_metric(cw : botocore.client.BaseClient, metrics: List[Dict[str, any]], namespace : str = "aws/Sagemaker/ModelBuildingPipeline/data-metrics"):
    for m in metrics:
        logger.info(f'Putting metric: {m["metric_name"]} value: {m["metric_value"]}')
        metric_data =[
                {
                    "MetricName": m["metric_name"],
                    "Dimensions": [{"Name": "PipelineName", "Value": m["pipeline_name"]}],
                    "Timestamp": datetime.utcnow(),
                    "Value": m["metric_value"],
                    "Unit": "None",
                },
            ]
        logger.info(f"Publishing metric data to Cloudwatch metrics @ namespace {namespace}. Timezone is UTC")
        logger.info(metric_data)
        response = cw.put_metric_data(
            Namespace=namespace,
            MetricData= metric_data,
        )
        logger.info(response)

if __name__ == "__main__":
    # parse_args
    args : argparse.Namespace = parse_arguments()
    #
    set_logging_level(level=args.logging_level)
    print_args(args)
    cw : botocore.client.BaseClient = cloudwatch_session()
    eb :  botocore.client.BaseClient = eventbridge_session()


    if (args.update_rules == 'True'):
        update_eventbridge_rules(
            eb=eb,
            sns_notification_arn=args.sns_notification_arn,
            pipeline_name= args.pipeline_name,
            sns_custom_arn=args.sns_custom_notification_arn,
            pipeline=args.pipeline_arn
        )
        update_alarms(cw=cw, namespace=args.metrics_namespace, pipeline_name= args.pipeline_name, sns_notification_arn=args.sns_notification_arn)

    violations : Dict[str, List[Dict[str, any]]] = load_file(violations_file=args.violations_file)
    formatter = locals()[args.framework]
    metrics : List[Dict[str, any]]  = list(formatter(pipeline_name=args.pipeline_name, feature=violations))
    put_cloudwatch_metric(cw = cw, metrics=metrics, namespace=args.metrics_namespace)
    #update alarm(cw)
