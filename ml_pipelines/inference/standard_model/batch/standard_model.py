import sagemaker
from sagemaker import ScriptProcessor
from sagemaker.network import NetworkConfig
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.sklearn import SKLearnProcessor
from sagemaker.workflow.parameters import ParameterInteger, ParameterString
from sagemaker.workflow.pipeline import Pipeline
import time
from sagemaker.workflow.check_job_config import CheckJobConfig
from sagemaker.workflow.quality_check_step import (
    DataQualityCheckConfig,
    QualityCheckStep,
)
from sagemaker.model_monitor.dataset_format import DatasetFormat
from sagemaker.workflow.functions import Join
from sagemaker.workflow.steps import (
    ProcessingStep,
    CacheConfig,
)
from sagemaker.workflow.execution_variables import ExecutionVariables



# - ExecutionVariables.START_DATETIME
# - ExecutionVariables.CURRENT_DATETIME
# - ExecutionVariables.PIPELINE_NAME
# - ExecutionVariables.PIPELINE_ARN
# - ExecutionVariables.PIPELINE_EXECUTION_ID
# - ExecutionVariables.PIPELINE_EXECUTION_ARN
# - ExecutionVariables.TRAINING_JOB_NAME
# - ExecutionVariables.PROCESSING_JOB_NAME

def standard_model_pipeline(base_job_prefix, default_bucket, env_data, model_package_group_name, pipeline_name, region,
                            sagemaker_session, base_dir, source_scripts_path, model_metadata, project = "standard_model", revision = "none", purpose = "p1033" ):
    #time = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    epoch_time = int(time.time())
    #data_bucket + prefix = s3://${DATA_BUCKET_ENV}/lifecycle/60d/${SAGEMAKER_PROJECT_NAME}/${PIPELINE_NAME}/${TRIGGER_ID}/p1033"

    batch_data, data_bucket, dataquality_input, dataquality_output, inference_output, purpose_param, trigger_id = data_paths(
        env_data, pipeline_name, project, purpose, model_metadata)

    subnet1 = ParameterString(name="Subnet1", default_value="{}".format(env_data["SubnetIds"][0]))
    subnet2 = ParameterString(name="Subnet2", default_value="{}".format(env_data["SubnetIds"][1]))
    securitygroup = ParameterString(name="SecurityGroup", default_value="{}".format(env_data["SecurityGroups"][0]))
    volume_kms_key = ParameterString(name="EbsKmsKeyArn", default_value="{}".format(env_data["EbsKmsKeyArn"]))
    output_kms_key = ParameterString(name="S3KmsKeyId", default_value="{}".format(env_data["S3KmsKeyId"]))
    processing_role = ParameterString(name="ProcessingRole")
    source_account = ParameterString(name="SourceAccount")
    processing_instance_count = ParameterInteger(name="ProcessingInstanceCount", default_value=1)
    processing_instance_type = ParameterString(name="ProcessingInstanceType", default_value="ml.m5.xlarge" )

    database = ParameterString(name="DataBase", default_value="ml-test-datasets_rl" )
    table = ParameterString(name="AbaloneTable", default_value="ml_abalone" )
    filter = ParameterString(name="FilterRings", default_value="disabled")


    notification_sns = ParameterString(name="NotificationSNS", default_value="")
    custom_sns = ParameterString(name="CustomSNS", default_value="")
    update_cw_rules = ParameterString(name="UpdateCloudWatchRules", default_value="False")

    nowgmt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    execution_time = ParameterString(name="ExecutionTime", default_value=nowgmt)
    custom_payload = ParameterString(name="CustomPayload", default_value="{}")
    execution_date = ParameterString(name="ExecutionDate", default_value=nowgmt)
    tenant = ParameterString(name="Tenant", default_value="tenant")
    bydf_param_name = ParameterString(name="BydfParamName", default_value="BringYourOwnDataFoundation")

    # configure network for encryption, network isolation and VPC configuration
    # Since the preprocessor job takes the data from S3, enable_network_isolation must be set to False
    # see https://github.com/aws/amazon-sagemaker-examples/issues/1689
    network_config = NetworkConfig(
        enable_network_isolation=False,
        security_group_ids=[securitygroup],
        subnets=[subnet1, subnet2],
        encrypt_inter_container_traffic=True)

    vpc_config = {
        "Subnets": network_config.subnets,
        "SecurityGroupIds": network_config.security_group_ids
    }
    step_process = preprocessing(base_job_prefix=base_job_prefix,
                                 network_config=network_config,
                                 processing_instance_count=processing_instance_count,
                                 processing_instance_type=processing_instance_type,
                                 sagemaker_session=sagemaker_session,
                                 preprocess_script_path="{}/preprocessing/preprocess.py".format(source_scripts_path), #if you instead want to use same as from training use> model_metadata["CustomerMetadataProperties"]["preprocess"],
                                 batch_data=batch_data,
                                 database=database,
                                 table=table,
                                 filter=filter,
                                 volume_kms_key=volume_kms_key,
                                 output_kms_key=output_kms_key,
                                 processing_role=processing_role,
                                 execution_time=execution_time,
                                 custom_payload=custom_payload,
                                 execution_date=execution_date,
                                 tenant=tenant,
                                 bydf_param_name=bydf_param_name
    )

    image_uri = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.0-1",
        py_version="py3",
        instance_type='ml.m5.xlarge',
    )
    step_custom_inference =  inference_custom_tasks(base_job_prefix=base_job_prefix,
                               env_data=env_data,
                               image_uri=image_uri,
                               network_config=network_config,
                               sagemaker_session=sagemaker_session,
                               step_process=step_process,
                               processing_instance_type=processing_instance_type,
                               source_scripts_path=source_scripts_path,
                               model_metadata=model_metadata,
                               output_data_path=inference_output,
                               dataquality_input=dataquality_input,
                               processing_instance_count=processing_instance_count,
                               volume_kms_key=volume_kms_key,
                               output_kms_key=output_kms_key,
                               processing_role=processing_role
                               )

    step_custom_inference.add_depends_on([step_process])
    step_monitor,step_monitor_process = baseline_monitor_task(
        env_data=env_data,
        base_job_prefix=base_job_prefix,
        network_config=network_config,
        volume_kms_key=volume_kms_key,
        output_kms_key=output_kms_key,
        processing_role=processing_role,
        sagemaker_session=sagemaker_session,
        processing_instance_type=processing_instance_type,
        pipeline_name=pipeline_name,
        region=region,
        step_custom_inference=step_custom_inference ,
        dataquality_output=dataquality_output,
        model_metadata=model_metadata,
        source_scripts_path=source_scripts_path,
        notification=notification_sns,
        custom_notification=custom_sns,
        update_rules=update_cw_rules
    )

    step_monitor.add_depends_on([step_custom_inference])
    step_monitor_process.add_depends_on([step_monitor])
    step_postprocess = postprocessing(base_job_prefix=base_job_prefix,
                                 network_config=network_config,
                                 processing_instance_count=processing_instance_count,
                                 processing_instance_type=processing_instance_type,
                                 sagemaker_session=sagemaker_session,
                                 postprocess_script_path="{}/postprocessing/postprocess.py".format(source_scripts_path), #if you instead want to use same as from training use> model_metadata["CustomerMetadataProperties"]["postprocess"],
                                 volume_kms_key=volume_kms_key,
                                 output_kms_key=output_kms_key,
                                 processing_role=processing_role,
                                 trigger_id=trigger_id,
                                 inference_output=inference_output,
                                source_account=source_account,
                                bydf_param_name=bydf_param_name
    )

    step_postprocess.add_depends_on([step_monitor_process])


    # pipeline instance
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            subnet1,
            subnet2,
            securitygroup,
            processing_instance_count,
            processing_instance_type,
            volume_kms_key,
            output_kms_key,
            processing_role,
            data_bucket,
            purpose_param,
            trigger_id,
            source_account,
            execution_time,
            custom_payload,
            execution_date,
            tenant,
            bydf_param_name,
            database,
            table,
            filter,
            notification_sns,
            custom_sns,
            update_cw_rules
        ],
        steps=[step_process, step_custom_inference, step_monitor, step_monitor_process, step_postprocess],
        sagemaker_session=sagemaker_session,
    )
    return pipeline


def data_paths(env_data, pipeline_name, project, purpose, model_metadata):
    data_bucket = ParameterString(name="DataBucket", default_value=env_data["DataBucketName"])
    purpose_param = ParameterString(name="Purpose", default_value=purpose)
    trigger_id = ParameterString(name="TriggerID",
                                 default_value="0000000000")  # from codebuild - use CODEBUILD_BUILD_ID env variable parsed after ":" The CodeBuild ID of the build (for example, codebuild-demo-project:b1e6661e-e4f2-4156-9ab9-82a19EXAMPLE).
    prefix_path = Join(on='/', values=["lifecycle/60d", project, pipeline_name, model_metadata["CustomerMetadataProperties"]["pipeline_execution_id"], ExecutionVariables.PIPELINE_EXECUTION_ID, purpose_param])
    data_base_path = Join(on='/', values=['s3:/', data_bucket, prefix_path])
    batch_data = Join(on='/', values=[data_base_path, 'model-input'])
    inference_output = Join(on='/', values=[data_base_path, 'inference-output'])
    dataquality_input = Join(on='/', values=[data_base_path, 'dataquality-input'])
    dataquality_output = Join(on='/', values=[data_base_path, 'dataquality-output'])
    return batch_data, data_bucket, dataquality_input, dataquality_output, inference_output, purpose_param, trigger_id


def baseline_monitor_task(
        env_data,
        base_job_prefix,
        network_config,
        volume_kms_key,
        output_kms_key,
        processing_role,
        sagemaker_session,
        processing_instance_type,
        pipeline_name,
        region,
        step_custom_inference,
        dataquality_output,
        model_metadata,
        source_scripts_path,
        custom_notification,
        notification,
        update_rules="True"):
    check_job_config = CheckJobConfig(
        role=processing_role,
        instance_count=1,
        instance_type=processing_instance_type,
        sagemaker_session=sagemaker_session,
        base_job_name=f"{base_job_prefix}/monitoring",
        env = {
            "PipelineName": pipeline_name,
            "Region": region,
        },
        network_config = network_config,
        volume_kms_key= volume_kms_key,
        output_kms_key= output_kms_key,
    )

    data_quality_check_config = DataQualityCheckConfig(
        baseline_dataset=step_custom_inference.properties.ProcessingOutputConfig.Outputs["inference-with-features"].S3Output.S3Uri,
        dataset_format=DatasetFormat.csv(header=False),
        output_s3_uri= dataquality_output,
    )

    step_monitor = QualityCheckStep(
        name="ModelMonitor",
        skip_check=False,
        register_new_baseline=False,
        fail_on_violation=False,
        quality_check_config=data_quality_check_config,
        check_job_config=check_job_config,
        supplied_baseline_statistics = model_metadata["ModelMetrics"]["ModelDataQuality"]["Statistics"]["S3Uri"], #os.path.join(baseline_uri, "statistics.json"),
        supplied_baseline_constraints = model_metadata["ModelMetrics"]["ModelDataQuality"]["Constraints"]["S3Uri"], #os.path.join(baseline_uri, "constraints.json"),
    )

    cache_config = CacheConfig(enable_caching=True, expire_after="PT3H")
    # processing step for monitoring tasks
    sklearn_processor = SKLearnProcessor(
        framework_version="1.0-1",
        instance_type=processing_instance_type,
        instance_count=1,
        base_job_name=f"{base_job_prefix}/monitor",
        sagemaker_session=sagemaker_session,
        role=processing_role,
        network_config=network_config,
        volume_kms_key=volume_kms_key,
        output_kms_key=output_kms_key
    )

    step_monitor_process = ProcessingStep(
        name="DataQualityPostProcess",
        cache_config=cache_config,
        processor=sklearn_processor,
        inputs=[ # step_monitor.quality_check_config
            ProcessingInput(
                source=step_monitor.quality_check_config.output_s3_uri,
                destination="/opt/ml/processing/monitoring/input/"
            )
            ],
        code="{}/monitoring/postprocess_monitor_script.py".format(source_scripts_path),
        job_arguments=[
            "--pipeline-name", pipeline_name,
            "--pipeline-arn", ExecutionVariables.PIPELINE_ARN,
            "--sns-notification-arn", notification, #@todo needs to be created an ssm that we fetch to populate per env. probably trough sm pipeline parameter
            "--sns-custom-notification-arn", custom_notification,
            "--update-rules", update_rules,
            "--metrics-namespace", "aws/Sagemaker/ModelBuildingPipeline/data-metrics",
            "--framework", "deequ",
            "--violations-file","/opt/ml/processing/monitoring/input/constraint_violations.json",
            "--logging-level", "INFO"
        ],
    )
    return step_monitor,step_monitor_process

def preprocessing(base_job_prefix,
                  network_config,
                  processing_instance_count,
                  processing_instance_type,
                  sagemaker_session,
                  preprocess_script_path,
                  batch_data,
                  volume_kms_key,
                  output_kms_key,
                  database,
                  table,
                  filter,
                  processing_role,
                  execution_time,
                  custom_payload,
                  execution_date,
                  tenant,
                  bydf_param_name
                  ):
    cache_config = CacheConfig(enable_caching=True, expire_after="PT3H")

    # processing step for feature engineering
    sklearn_processor = SKLearnProcessor(
        framework_version="0.23-1",
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/preprocess",
        sagemaker_session=sagemaker_session,
        role=processing_role,
        network_config=network_config,
        volume_kms_key=volume_kms_key,
        output_kms_key=output_kms_key
    )

    step_process = ProcessingStep(
        name="Preprocess",
        cache_config=cache_config,
        processor=sklearn_processor,
        outputs=[
            ProcessingOutput(output_name="inference",
                             source="/opt/ml/processing/inference-test/",
                             destination=batch_data
                             ),
        ],
        code=preprocess_script_path,
        job_arguments=[
            "--context", "inference",
            "--executiontime", execution_time,
            "--custom-payload", custom_payload,
            "--executiondate", execution_date,
            "--tenant", tenant,
            "--database", database,
            "--table", table,
            "--filter", filter,
            "--start_datetime", ExecutionVariables.START_DATETIME,
            "--current_datetime", ExecutionVariables.CURRENT_DATETIME,
            "--pipeline_name", ExecutionVariables.PIPELINE_NAME,
            "--pipeline_arn", ExecutionVariables.PIPELINE_ARN,
            "--pipeline_execution_id", ExecutionVariables.PIPELINE_EXECUTION_ID,
            "--pipeline_execution_arn", ExecutionVariables.PIPELINE_EXECUTION_ARN,
            "--bydf-param-name", bydf_param_name
        ],
    )

    # - "START_DATETIME", ExecutionVariables.START_DATETIME,
    # - "CURRENT_DATETIME", ExecutionVariables.CURRENT_DATETIME,
    # - "PIPELINE_NAME", ExecutionVariables.PIPELINE_NAME,
    # - "PIPELINE_ARN", ExecutionVariables.PIPELINE_ARN,
    # - "PIPELINE_EXECUTION_ID", ExecutionVariables.PIPELINE_EXECUTION_ID,
    # - "PIPELINE_EXECUTION_ARN", ExecutionVariables.PIPELINE_EXECUTION_ARN,
    # - "TRAINING_JOB_NAME", ExecutionVariables.TRAINING_JOB_NAME,
    # - "PROCESSING_JOB_NAME", ExecutionVariables.PROCESSING_JOB_NAME,

    return step_process

def inference_custom_tasks(
        base_job_prefix,
        env_data,
        image_uri,
        network_config,
        processing_instance_type,
        sagemaker_session,
        step_process,
        source_scripts_path,
        model_metadata,
        output_data_path,
        dataquality_input,
        processing_instance_count,
        volume_kms_key,
        output_kms_key,
        processing_role,
):
    script_eval = ScriptProcessor(
        image_uri=image_uri,
        command=["python3"],
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/inference",
        sagemaker_session=sagemaker_session,
        role=processing_role,
        network_config=network_config,
        volume_kms_key=volume_kms_key,
        output_kms_key=output_kms_key
    )
    cache_config = CacheConfig(enable_caching=True, expire_after="PT8H")

    inference_step = ProcessingStep(
        name="Inference",
        cache_config=cache_config,
        processor=script_eval,
        inputs=[
            ProcessingInput(
                source=model_metadata["InferenceSpecification"]["Containers"][0]["ModelDataUrl"],
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=step_process.properties.ProcessingOutputConfig.Outputs[
                    "inference"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/inference",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="inference-output", source="/opt/ml/processing/inference-output",
                             destination= output_data_path
                             ),
            ProcessingOutput(output_name="inference-with-features", source="/opt/ml/processing/inference-with-features",
                             destination= dataquality_input
                             ),

        ],
        code="{}/inference/inference.py".format(source_scripts_path),
    )

    return inference_step

def postprocessing(base_job_prefix,
                   network_config,
                  processing_instance_count,
                  processing_instance_type,
                  sagemaker_session,
                  postprocess_script_path,
                  volume_kms_key,
                  output_kms_key,
                  processing_role,
                  trigger_id,
                  inference_output,
                   source_account,
                   bydf_param_name
                  ):

    # processing step for post processing after inference
    sklearn_processor = SKLearnProcessor(
        framework_version="0.23-1",
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/NotifyDataFoundation",
        sagemaker_session=sagemaker_session,
        role=processing_role,
        network_config=network_config,
        volume_kms_key=volume_kms_key,
        output_kms_key=output_kms_key
    )

    post_process = ProcessingStep(
        name="NotifyDataFoundation",
        processor=sklearn_processor,
        code=postprocess_script_path,
        job_arguments=[
            "--context", "postprocess",
            "--triggerid", trigger_id,
            "--inferenceoutput", inference_output,
            "--sourceaccount", source_account,
            "--bydf-param-name", bydf_param_name
        ]
    )


    return post_process