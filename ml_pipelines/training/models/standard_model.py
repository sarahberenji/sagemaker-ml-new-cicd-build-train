import sagemaker
from sagemaker import ScriptProcessor, TrainingInput
from sagemaker.estimator import Estimator
from sagemaker.network import NetworkConfig
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.sklearn import SKLearnProcessor
from sagemaker.workflow.condition_step import JsonGet, ConditionStep
from sagemaker.workflow.conditions import ConditionLessThanOrEqualTo
from sagemaker.workflow.execution_variables import ExecutionVariables
from sagemaker.workflow.parameters import ParameterInteger, ParameterString
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.step_collections import RegisterModel
from datetime import datetime
import time
def standard_model_pipeline(base_job_prefix, default_bucket, env_data, model_package_group_name, pipeline_name, region,
                            sagemaker_session, base_dir, source_scripts_path, project = "standard_model", revision = "none", purpose = "p1033" ):
    # parameters for pipeline execution
    model_approval_status, processing_instance_count, processing_instance_type, training_instance_type = sagemaker_pipeline_parameters(
        data_bucket=default_bucket)
    database = ParameterString(name="DataBase", default_value="ml-test-datasets_rl" )
    table = ParameterString(name="AbaloneTable", default_value="ml_abalone" )
    filter = ParameterString(name="FilterRings", default_value="disabled")
    time_path = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    trigger_id = ParameterString(name="TriggerID", default_value="0000000000") #from codebuild - use CODEBUILD_BUILD_ID env variable parsed after ":" The CodeBuild ID of the build (for example, codebuild-demo-project:b1e6661e-e4f2-4156-9ab9-82a19EXAMPLE).
    nowgmt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    execution_time = ParameterString(name="ExecutionTime", default_value=nowgmt)
    custom_payload = ParameterString(name="CustomPayload", default_value="{}")
    execution_date = ParameterString(name="ExecutionDate", default_value=nowgmt)
    tenant = ParameterString(name="Tenant", default_value="tenant")
    #@todo parameterize and use  this data path   prefix_path = Join(on='/', values=["lifecycle/60d", project, pipeline_name, ExecutionVariables.PIPELINE_EXECUTION_ID, purpose_param])
    #data_base_path="s3://{}/lifecycle/60d/{}/{}/{}/{}/output/training".format(env_data["DataBucketName"], project, pipeline_name, revision, time_path, purpose)
    #data_base_path = Join(on='/', values=["s3:/",env_data["DataBucketName"],"lifecycle/60d", project, pipeline_name, ExecutionVariables.PIPELINE_EXECUTION_ID, purpose])
    prefix_path = Join(on='/', values=["lifecycle/60d", project, pipeline_name, ExecutionVariables.PIPELINE_EXECUTION_ID])
    data_base_path = Join(on='/', values=['s3:/', env_data["DataBucketName"], prefix_path, purpose])

    model_base_path = Join(on='/', values=['s3:/', env_data["ModelBucketName"], prefix_path])
    model_path = Join(on='/', values=[model_base_path, "model"])
    baseline_path = Join(on='/', values=[model_base_path, "data-monitoring"])
    evaluation_path = Join(on='/', values=[model_base_path, "evaluation"])

    bydf_param_name = ParameterString(name="BydfParamName", default_value="BringYourOwnDataFoundation")
    #model_path = "s3://{}/lifecycle/max/{}/{}/{}/{}/training".format(env_data["ModelBucketName"], project,  pipeline_name, revision, model_name, time_path)
    #baseline_path = "s3://{}/lifecycle/max/{}/{}/{}/{}/data-monitoring".format(env_data["ModelBucketName"], project,  pipeline_name, revision, model_name, time_path)
    #evaluation_path = "s3://{}/lifecycle/max/{}/{}/{}/{}/evaluation".format(env_data["ModelBucketName"], project, pipeline_name, revision, model_name, time_path)
    # configure network for encryption, network isolation and VPC configuration
    # Since the preprocessor job takes the data from S3, enable_network_isolation must be set to False
    # see https://github.com/aws/amazon-sagemaker-examples/issues/1689
    network_config = NetworkConfig(
        enable_network_isolation=False,
        security_group_ids=env_data["SecurityGroups"],
        subnets=env_data["SubnetIds"],
        encrypt_inter_container_traffic=True)

    step_process, preprocessing_script = preprocessing(
        base_job_prefix=base_job_prefix,
        env_data=env_data,
        network_config=network_config,
        processing_instance_count=processing_instance_count,
        processing_instance_type=processing_instance_type,
        sagemaker_session=sagemaker_session,
        source_scripts_path=source_scripts_path,

        raw_path=Join(on='/', values=[data_base_path, "raw"]),
        training_path=Join(on='/', values=[data_base_path, "training"]),
        validation_path=Join(on='/', values=[data_base_path, "validation"]),
        test_path=Join(on='/', values=[data_base_path, "test"]),
        database=database,
        table=table,
        filter=filter,
        execution_time=execution_time,
        custom_payload=custom_payload,
        execution_date=execution_date,
        tenant=tenant,
        bydf_param_name=bydf_param_name
    )
    # training step for generating model artifacts
    image_uri = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.0-1",
        py_version="py3",
        instance_type=training_instance_type,
    )

    step_baseline, drift_check_baselines = baseline_tasks(
        env_data=env_data,
        sagemaker_session=sagemaker_session,
        processing_instance_type=processing_instance_type,
        step_process=step_process,
        baseline_path = baseline_path,
        model_package_group_name=model_package_group_name,
        network_config=network_config,
        source_scripts_path=source_scripts_path
    )


    step_train, xgb_train = training_tasks(base_job_prefix=base_job_prefix,
                                           env_data=env_data,
                                           image_uri=image_uri,
                                           network_config=network_config,
                                           sagemaker_session=sagemaker_session,
                                           step_process=step_process,
                                           training_instance_type=training_instance_type,
                                           model_path = model_path
                                           )
    # processing step for evaluation

    evaluation_report, model_metrics, step_eval = evaluation_tasks(base_job_prefix=base_job_prefix,
                                                                   env_data=env_data,
                                                                   image_uri=image_uri,
                                                                   network_config=network_config,
                                                                   sagemaker_session=sagemaker_session,
                                                                   step_process=step_process,
                                                                   processing_instance_type=processing_instance_type,
                                                                   step_train=step_train,
                                                                   source_scripts_path=source_scripts_path,
                                                                   evaluation_path = evaluation_path,
                                                                   step_baseline=step_baseline
                                                                   )
    
    postprocessing_script="{}/postprocessing/postprocess.py".format(source_scripts_path)
    step_cond = model_register_tasks(evaluation_report,
                                     model_approval_status,
                                     model_metrics,
                                     model_package_group_name,
                                     network_config,
                                     step_eval,
                                     step_train,
                                     xgb_train,
                                     preprocessing_script,
                                     postprocessing_script,
                                     revision,
                                     source_scripts_path,
                                     drift_check_baselines)
    # pipeline instance
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_type,
            processing_instance_count,
            training_instance_type,
            model_approval_status,
            trigger_id,
            execution_time,
            custom_payload,
            execution_date,
            tenant,
            database,
            table,
            filter,
            bydf_param_name,
        ],
        steps=[step_process, step_baseline, step_train, step_eval, step_cond],
        # steps=[step_process],
        sagemaker_session=sagemaker_session,
    )
    return pipeline


def sagemaker_pipeline_parameters(data_bucket):
    processing_instance_count = ParameterInteger(name="ProcessingInstanceCount", default_value=1)
    processing_instance_type = ParameterString(
        name="ProcessingInstanceType", default_value="ml.m5.xlarge"
    )
    training_instance_type = ParameterString(
        name="TrainingInstanceType", default_value="ml.m5.xlarge"
    )
    model_approval_status = ParameterString(
        name="ModelApprovalStatus", default_value="PendingManualApproval"
    )

    return model_approval_status, processing_instance_count, processing_instance_type, training_instance_type


def preprocessing(base_job_prefix,
                  env_data,
                  network_config,
                  processing_instance_count,
                  processing_instance_type,
                  sagemaker_session,
                  source_scripts_path,
                  raw_path,
                  training_path,
                  validation_path,
                  test_path,
                  database,
                  table,
                  filter,
                  execution_time,
                  custom_payload,
                  execution_date,
                  tenant,
                  bydf_param_name
                  ):
    preprocessing_script = "{}/preprocessing/preprocess.py".format(source_scripts_path)
    cache_config = CacheConfig(enable_caching=True, expire_after="PT8H")

    # processing step for feature engineering
    sklearn_processor = SKLearnProcessor(
        framework_version="0.23-1",
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/preprocess",
        sagemaker_session=sagemaker_session,
        role=env_data["ProcessingRole"],
        network_config=network_config,
        volume_kms_key=env_data["EbsKmsKeyArn"],
        output_kms_key=env_data["S3KmsKeyId"]
    )

    step_process = ProcessingStep(
        name="Preprocess",
        cache_config=cache_config,
        processor=sklearn_processor,
        outputs=[
            ProcessingOutput(
                output_name="raw",
                source="/opt/ml/processing/raw",
                destination=raw_path
            ),
            ProcessingOutput(
                output_name="train",
                source="/opt/ml/processing/train",
                destination=training_path
            ),
            ProcessingOutput(output_name="validation",
                             source="/opt/ml/processing/validation",
                             destination=validation_path
                             ),
            ProcessingOutput(output_name="test",
                             source="/opt/ml/processing/test",
                             destination=test_path
                             )
        ],
        code = preprocessing_script,
        job_arguments=[
            "--context", "training",
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
    return step_process, preprocessing_script
from sagemaker.drift_check_baselines import DriftCheckBaselines
from sagemaker.workflow.check_job_config import CheckJobConfig
from sagemaker.workflow.quality_check_step import (
    DataQualityCheckConfig,
    ModelQualityCheckConfig,
    QualityCheckStep,
)
from sagemaker.model_monitor.dataset_format import DatasetFormat
from sagemaker.model_metrics import (
    MetricsSource,
    ModelMetrics,
)
from sagemaker.workflow.functions import Join
from sagemaker.workflow.steps import (
    ProcessingStep,
    TrainingStep,
    CacheConfig,
)
#@todo fix baseline definition and run to register in model reg with model
def baseline_tasks(
    env_data,
    sagemaker_session,
    processing_instance_type,
    step_process,
    baseline_path,
    model_package_group_name,
    network_config,
    source_scripts_path
    ):

    check_job_config = CheckJobConfig(
        role=env_data["ProcessingRole"],
        instance_count=1,
        instance_type=processing_instance_type,
        sagemaker_session=sagemaker_session,
        network_config=network_config,
        volume_kms_key=env_data["EbsKmsKeyArn"],
        output_kms_key=env_data["S3KmsKeyId"]
    )

    data_quality_check_config = DataQualityCheckConfig(
        baseline_dataset=step_process.properties.ProcessingOutputConfig.Outputs["train"].S3Output.S3Uri,
        dataset_format=DatasetFormat.csv(header=False),
        output_s3_uri=baseline_path,
        post_analytics_processor_script="{}/monitoring/training_monitor_script.py".format(source_scripts_path)
    )
    cache_config = CacheConfig(enable_caching=False, expire_after="PT1H")
    step_baseline = QualityCheckStep(
        name="DataQualityBaselineJob",
        skip_check=True,
        fail_on_violation=False,
        register_new_baseline=True,
        quality_check_config=data_quality_check_config,
        check_job_config=check_job_config,
        model_package_group_name=model_package_group_name,
        cache_config=cache_config,
    )

    drift_check_baselines = DriftCheckBaselines(
        model_data_statistics=MetricsSource(
            s3_uri=step_baseline.properties.BaselineUsedForDriftCheckStatistics,
            content_type="application/json",
        ),
        model_data_constraints=MetricsSource(
            s3_uri=step_baseline.properties.BaselineUsedForDriftCheckConstraints,
            content_type="application/json",
        ),
    )

    return step_baseline, drift_check_baselines

def training_tasks(base_job_prefix, env_data, image_uri, network_config, sagemaker_session, step_process,
                   training_instance_type, model_path):
    xgb_train = Estimator(
        image_uri=image_uri,
        instance_type=training_instance_type,
        instance_count=1,
        output_path=model_path,
        base_job_name=f"{base_job_prefix}/train",
        sagemaker_session=sagemaker_session,
        role=env_data["TrainingRole"],
        subnets=network_config.subnets,
        security_group_ids=network_config.security_group_ids,
        encrypt_inter_container_traffic=True,
        enable_network_isolation=False,
        volume_kms_key=env_data["EbsKmsKeyArn"],
        output_kms_key=env_data["S3KmsKeyId"]
    )
    cache_config = CacheConfig(enable_caching=True, expire_after="PT8H")

    xgb_train.set_hyperparameters(
        objective="reg:linear",
        num_round=50,
        max_depth=5,
        eta=0.2,
        gamma=4,
        min_child_weight=6,
        subsample=0.7,
        silent=0,
    )

    step_train = TrainingStep(
        name="TrainModel",
        estimator=xgb_train,
        cache_config=cache_config,
        inputs={
            "train": TrainingInput(
                s3_data=step_process.properties.ProcessingOutputConfig.Outputs[
                    "train"
                ].S3Output.S3Uri,
                content_type="text/csv",
            ),
            "validation": TrainingInput(
                s3_data=step_process.properties.ProcessingOutputConfig.Outputs[
                    "validation"
                ].S3Output.S3Uri,
                content_type="text/csv",
            ),
        },
    )
    return step_train, xgb_train


def evaluation_tasks(base_job_prefix, env_data, image_uri, network_config, processing_instance_type, sagemaker_session,
                     step_process, step_train, source_scripts_path, evaluation_path, step_baseline):
    script_eval = ScriptProcessor(
        image_uri=image_uri,
        command=["python3"],
        instance_type=processing_instance_type,
        instance_count=1,
        base_job_name=f"{base_job_prefix}/evaluation",
        sagemaker_session=sagemaker_session,
        role=env_data["ProcessingRole"],
        network_config=network_config,
        volume_kms_key=env_data["EbsKmsKeyArn"],
        output_kms_key=env_data["S3KmsKeyId"]
    )
    cache_config = CacheConfig(enable_caching=True, expire_after="PT8H")
    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )
    step_eval = ProcessingStep(
        name="EvaluateModel",
        processor=script_eval,
        cache_config=cache_config,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=step_process.properties.ProcessingOutputConfig.Outputs[
                    "test"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/test",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="evaluation", source="/opt/ml/processing/evaluation",
                             destination= evaluation_path
                             ),
        ],
        code="{}/evaluate/evaluate.py".format(source_scripts_path),
        property_files=[evaluation_report],
    )

    # register model step that will be conditionally executed
    model_metrics = ModelMetrics(
        model_statistics=MetricsSource(
            s3_uri=Join(on='/', values=[evaluation_path, "evaluation.json"]),

            content_type="application/json"
        ),
        model_data_statistics=MetricsSource(
            s3_uri=step_baseline.properties.CalculatedBaselineStatistics,
            content_type="application/json",
        ),
        model_data_constraints=MetricsSource(
            s3_uri=step_baseline.properties.CalculatedBaselineConstraints,
            content_type="application/json",
        ),
    )
    return evaluation_report, model_metrics, step_eval


def model_register_tasks(evaluation_report, model_approval_status, model_metrics, model_package_group_name,
                         network_config, step_eval, step_train, xgb_train, preprocessing_script, postprocessing_script, revision, source_scripts_path,
                         drift_check_baselines):
    """
    There is a bug in RegisterModel implementation
    The RegisterModel step is implemented in the SDK as two steps, a _RepackModelStep and a _RegisterModelStep.
    The _RepackModelStep runs a SKLearn training step in order to repack the model.tar.gz to include any custom inference code in the archive.
    The _RegisterModelStep then registers the repacked model.

    The problem is that the _RepackModelStep does not propagate VPC configuration from the Estimator object:
    https://github.com/aws/sagemaker-python-sdk/blob/cdb633b3ab02398c3b77f5ecd2c03cdf41049c78/src/sagemaker/workflow/_utils.py#L88

    This cause the AccessDenied exception because repacker cannot access S3 bucket (all access which is not via VPC endpoint is bloked by the bucket policy)

    The issue is opened against SageMaker python SDK: https://github.com/aws/sagemaker-python-sdk/issues/2302
    """
    vpc_config = {
        "Subnets": network_config.subnets,
        "SecurityGroupIds": network_config.security_group_ids
    }
    step_register = RegisterModel(
        name="Model",
        estimator=xgb_train,
        model_data=step_train.properties.ModelArtifacts.S3ModelArtifacts,
        content_types=["text/csv"],
        response_types=["text/csv"],
        inference_instances=["ml.t2.medium", "ml.m5.large"],
        transform_instances=["ml.m5.large"],
        model_package_group_name=model_package_group_name,
        approval_status=model_approval_status,
        model_metrics=model_metrics,
        drift_check_baselines=drift_check_baselines,
        vpc_config_override=vpc_config,
        customer_metadata_properties={
            "preprocess" : preprocessing_script,
            "postprocess" : postprocessing_script,
            "git_revision" : revision,
            "pipeline_execution_id" : ExecutionVariables.PIPELINE_EXECUTION_ID ,
            "pipeline_execution_arn" : ExecutionVariables.PIPELINE_EXECUTION_ARN

        }
    )

    # condition step for evaluating model quality and branching execution
    cond_lte = ConditionLessThanOrEqualTo(
        left=JsonGet(
            step=step_eval,
            property_file=evaluation_report,
            json_path="regression_metrics.mse.value"
        ),
        right=6.0,
    )
    step_cond = ConditionStep(
        name="CheckMSEEvaluation",
        conditions=[cond_lte],
        if_steps=[step_register],
        else_steps=[],
    )
    return step_cond
